"""
    Name:       Targeting Tools

    Authors:    International Center for Tropical Agriculture - CIAT
                Commonwealth Scientific and Industrial Research Organisation - CSIRO

    Notes:      Tool-1: Identify land suitable to cultivate a certain crop.
                Tool-2: Calculate statistics from the land suitability output raster
                        and return the result in a dbf file format.
                Tool-3: Identify areas that have similar biophysical characteristics to
                        the location currently under a certain type crop.
                Fully tested in ArcGIS 10.1.
                Requires Spatial Analyst extension

    Created:    May 2015
    Modified:   November 2015
"""
import arcgisscripting
import csv
import ntpath
import os
import re
import shlex
import shutil
import smtplib
import subprocess
import sys
import time
import traceback
from collections import OrderedDict

import arcpy

gp = arcgisscripting.create(9.5)
from itertools import *

arcpy.env.overwriteOutput = True

# Send Email when script is complete
SERVER = "smtp.gmail.com"
PORT = 587
FROM = 'targetingtools@gmail.com'
PASS = 'landsimilarity'
REST_URL = 'http://climatewizard.ciat.cgiar.org/arcgis/rest/'


def parameter(displayName, name, datatype, parameterType='Required',
              direction='Input', multiValue=False):
    param = arcpy.Parameter(
        displayName=displayName,
        name=name,
        datatype=datatype,
        parameterType=parameterType,
        direction=direction,
        multiValue=multiValue)
    return param


class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the .pyt file)."""
        self.label = "Targeting Tools"
        self.alias = "Target Tools"
        # List of tool classes associated with this toolbox
        self.tools = [LandSuitability, LandSimilarity, LandStatistics]


class TargetingTool(object):
    def isLicensed(self):
        """Set license to execute tool."""
        spatialAnalystCheckedOut = False
        if arcpy.CheckExtension('Spatial') == 'Available':
            arcpy.CheckOutExtension('Spatial')
            spatialAnalystCheckedOut = True
        else:
            arcpy.AddMessage(
                'ERROR: At a minimum, this script requires the Spatial Analyst '
                'Extension to run \n')
            sys.exit()
        return spatialAnalystCheckedOut

    def setRasSpatialWarning(self, ras_file, ras_ref, in_raster, prev_input):
        """ Set raster spatial warning
            Args:
                ras_file: Input raster file
                ras_ref: Input raster spatial reference
                in_raster: Input raster parameter
                prev_input: previous or preceding input raster with the true
                 spatial reference
            Return: None
        """
        last_spataial_ref = arcpy.Describe(
            ras_file).SpatialReference  # Get spatial reference
        for ref in ras_ref:
            warning_msg = "{0} spatial reference is different from the input {1}"
            self.setSpatialWarning(last_spataial_ref, ref, in_raster,
                                   warning_msg, ras_file, prev_input)

    def setFcSpatialWarning(self, in_parameter, ras_ref, prev_input):
        """ Sets feature class spatial warning
            Args:
                parameter: Feature class input parameter
                ras_ref: Input raster spatial reference
                prev_input: previous or preceding input raster with the true
                spatial reference
            Return: None
        """
        in_fc_param = in_parameter
        in_fc = in_parameter.valueAsText.replace("\\", "/")
        in_fc_spataial_ref = arcpy.Describe(in_fc).SpatialReference
        warning_msg = "{0} spatial reference is different from the input {1}"
        self.setSpatialWarning(
            in_fc_spataial_ref,
            ras_ref,
            in_fc_param,
            warning_msg,
            in_fc,
            prev_input
        )

    def send_message(self, tool, body, from_email, to_email):

        SUBJECT = '{} Output is Ready for Download'.format(tool)
        MSG = 'Dear Sir/Madam, \n\r' + \
              tool + ' processing has completed. \n' \
                     'This output will expire after 24 hours. \n' \
                     'Kindly download the output by clicking on the link below. \n' \
              + body + '\n\n' \
                       'Please respond to this email to send your feedback and support ' \
                       'question on the result and the tool. \n\n' \
                       'Regards, \n' \
                       'CIAT Land Targeting Tools Team\n\n'
        # Prepare actual message

        try:
            server = smtplib.SMTP(SERVER, PORT)
            server.ehlo()
            server.starttls()
            server.login(FROM, PASS)
            for email in to_email:
                message = """\
From: %s
To: %s
Subject: %s
""" % (FROM, email, SUBJECT)

                final_body = '\n\n{}\n'.format(MSG)

                messages = message + final_body
                server.sendmail(from_email, email, messages)
            server.close()
            arcpy.AddMessage('Successfully sent the result to your e-mail!')
        except:
            arcpy.AddMessage("Failed to send the result to your e-mail.")

    def submit_message(self, output_path, parameter, tool):
        if parameter is None:
            return
        emails = parameter.valueAsText
        if emails is None:
            return
        emails = emails.replace(" ", "")
        if ';' in emails:
            emails_list = emails.split(';')
        else:
            emails_list = emails.split(',')
        arcpy.AddMessage(emails)
        if len(emails) > 0:
            if not isinstance(output_path, OrderedDict):
                rel_path = output_path.split('arcgisserver/')
                if len(rel_path) > 1:
                    output_url = '{}{}'.format(REST_URL, rel_path[1])
                else:
                    output_url = output_path
            else:
                output_url_list = []
                for name, out_path in output_path.iteritems():
                    output_url_row = '{}\n{}'.format(name, out_path)
                    output_url_list.append(output_url_row)
                output_url = '\n'.join(output_url_list)

            self.send_message(tool, output_url,
                              FROM, emails_list)

    def setSpatialWarning(self, in_ras_ref, other_ref, tool_para, warning_msg,
                          new_in_ras, prev_in_ras):
        """ Sets spatial error message
            Args:
                in_ras_ref: Input data spatial reference
                other_ref: Other input data spatial reference
                tool_para: Tool parameter that will receive the warning
                warnign_msg: Spatial reference warning message
                new_in_ras: Other input data
                prev_in_ras: Input data itself
            Return: None
        """
        if in_ras_ref.Type != other_ref.Type:  # Check difference in spatial reference type
            tool_para.setWarningMessage(
                warning_msg.format(new_in_ras, prev_in_ras))
        elif in_ras_ref.Type != "Geographic":
            if in_ras_ref.PCSCode != other_ref.PCSCode:  # Check projection code
                tool_para.setWarningMessage(
                    warning_msg.format(new_in_ras, prev_in_ras))

    def uniqueValueValidator(self, prev_val, str_val, tool_para, field_id):
        """ Check for duplicates
            Args:
                prev_val: Prev values as list
                str_val: Input string value
                tool_para: Tool parameter that will receive the warning
                field_id: Availability of field identifier
            Returns: None
        """
        for item in prev_val:
            if str_val == item:
                if field_id:
                    if str_val != "#":
                        tool_para.setErrorMessage(
                            "{0} is a duplicate of {1}. This is not allowed".format(
                                str_val, item))
                    else:
                        tool_para.setErrorMessage("Column value is missing")
                else:
                    tool_para.setWarningMessage(
                        "{0} file is a duplicate of {1}".format(str_val, item))

    def getInputFc(self, parameter):
        """ Gets the input feature class
            Args:
                parameter: Tool parameters object
            Returns:
                in_fc_file: Input feature class file
                in_fc: Input feature class parameter
        """
        in_fc = parameter.valueAsText.replace("\\", "/")
        in_fc_file = ntpath.basename(in_fc)
        return {"in_fc": in_fc, "in_fc_file": in_fc_file}

    def getLayerDataSource(self, parameter):
        """ Gets current MXD layer data source
            Args:
                parameter: Tool parameters object
            Returns:
                in_fc_pt: Layer data source
        """
        in_fc_pt = ""
        mxd = arcpy.mapping.MapDocument("CURRENT")
        param_as_text = parameter.valueAsText.replace("\\", "/")
        if arcpy.mapping.ListLayers(mxd):  # Check if a layer exists
            for lyr in arcpy.mapping.ListLayers(mxd):
                if lyr.supports("datasetName"):
                    if lyr.name == param_as_text:
                        if lyr.supports("dataSource"):
                            in_fc_pt = lyr.dataSource.replace("\\", "/")
        return in_fc_pt

    def formatValueTableData(self, lst):
        """ Clean value table data
            Args:
                lst: Value table input raw data
            Return:
                lst_val: Value table input row data as list
        """
        lst_val = re.sub(r"'[^']*'", '""', lst).split()
        # Substitute quoted input string with empty quotes to create list
        if '""' in lst_val:
            counter = 0
            lst_quoted_val = []
            lst_quoted_re = re.compile("'[^']*'")  # Get quoted string input
            # Create list of quoted string input
            for item in lst_quoted_re.findall(lst):
                lst_quoted_val.append(item)
            # Replace empty quotes in list with quoted string inputs
            for j, str_val in enumerate(lst_val):
                if str_val == '""':
                    if counter < len(lst_quoted_val):
                        lst_val[j] = self.trimString(lst_quoted_val[counter])
                    counter += 1
        return lst_val

    def trimString(self, in_str):
        """ Trim leading and trailing quotation mark
            Args:
                in_str: String to be cleaned
            Return:
                out_str: Cleaned string
        """
        if in_str.startswith("'"):
            in_str = in_str.lstrip("'")
        if in_str.endswith("'"):
            in_str = in_str.rstrip("'")
        return in_str

    def setFileNameLenError(self, out_ras_param):
        """ Set ESRI GRID file name length error
            Args:
                out_ras_param: Out file parameter
            Return: None
        """
        if out_ras_param.value and out_ras_param.altered:
            out_ras = out_ras_param.valueAsText.replace("\\", "/")
            out_ras_file, out_ras_file_ext = os.path.splitext(out_ras)
            if out_ras_file_ext != ".tif":
                if len(ntpath.basename(out_ras)) > 13:
                    out_ras_param.setErrorMessage(
                        "Output raster: The length of the grid base "
                        "name in {0} is longer than 13.".format(
                            out_ras.replace("/", "\\")))

    def setDuplicateNameError(self, out_ras_1, out_ras_2):
        """ Set duplicate file name error
            Args:
                out_ras_1: Primary parameter
                out_ras_2: Secondary parameter
            Return: None
        """
        if out_ras_1.value and out_ras_1.altered:
            if out_ras_2.value:
                if out_ras_1.valueAsText == out_ras_2.valueAsText:
                    out_ras_1.setErrorMessage(
                        "Duplicate output names are not allowed")

    def deleteFile(self, ras_temp_path, *args):
        """ Delete table, feature class or raster files
            Args:
                ras_temp_path: Temporary folder
                *arg: File paths
            Returns: None
        """
        for arg in args:
            if arcpy.Exists(ras_temp_path + arg):
                arcpy.management.Delete(ras_temp_path + arg)

    def loadOutput(self, out_ras):
        """ Loads output to the current MXD
            Args:
                parameters: Tool parameters object
                out_ras: Raster dataset - string or list
            Return: None
        """
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = arcpy.mapping.ListDataFrames(mxd, "*")[
            0]  # Get the first data frame
        # Load raster dataset to the current mxd

        if isinstance(out_ras, list):  # Check if it is a list
            for data_obj in out_ras:
                lyr = arcpy.mapping.Layer(data_obj)
                arcpy.mapping.AddLayer(df, lyr, "AUTO_ARRANGE")
        else:
            lyr = arcpy.mapping.Layer(out_ras)
            arcpy.mapping.AddLayer(df, lyr, "AUTO_ARRANGE")

    def calculateStatistics(self, in_raster):
        """
        Gets raster maximum value
        :param in_raster: Input raster absolute path
        :return: A raster with statistics calculated
        :rtype: Integer or float
        """
        if arcpy.Exists(in_raster):
            try:
                arcpy.GetRasterProperties_management(in_raster, "STD")
            except arcpy.ExecuteError:
                arcpy.CalculateStatistics_management(
                    in_raster, "1", "1", "", "OVERWRITE"
                )
            return arcpy.Raster(in_raster)

    def get_srid_from_file(self, first_in_raster):
        dsc = arcpy.Describe(first_in_raster)
        spatial_ref = dsc.spatialReference
        return spatial_ref

    def copyDataset(self, ras_temp_path, source_file, new_file):
        """ Copy dataset from one source to another
            Args:
                ras_temp_path: Temporary folder
                source_file: Source file
                new_file: New file
            Returns:
                new_file: New file path
        """
        if new_file is not None:
            new_file = ntpath.basename(new_file)
        else:
            new_file = ntpath.basename(source_file)
        # Copy point layer to a temporary directory
        arcpy.Copy_management(source_file, ras_temp_path + new_file)
        new_file = ras_temp_path + new_file
        return new_file


class LandSuitability(TargetingTool):
    def __init__(self):
        # TODO make sure all outputs are saved in scratch workspace folder
        """Define the tool (tool name is the name of the class)."""
        self.label = "Land Suitability"
        self.description = "Given a set of raster data and user optimal values, the Land Suitability tool determines the" \
                           " most suitable place to carry out an activity. In agriculture, it could be used to identify" \
                           " places with the best biophysical and socioeconomic conditions for a certain crop to do well."
        self.canRunInBackground = False
        self.value_table_cols = 6
        self.spatial_ref = None
        self.parameters = []

    # def create_value_table_params(self):
    #     parms = []
    #
    #     for i in range(1, 11):
    #         if i == 1:
    #             type = 'Required'
    #         else:
    #             type = 'Optional'
    #         self.parameters.append(
    #             parameter('Raster Layer {}'.format(i), "in_raster{}".format(i),
    #                       "Raster Layer",
    #                       parameterType=type))
    #         self.parameters.append(
    #             parameter('Min Value {}'.format(i), "min_val{}".format(i),
    #                       "GPDouble",
    #                       parameterType=type))
    #         self.parameters.append(
    #             parameter('Optimal From {}'.format(i), "opti_from{}".format(i),
    #                       "GPDouble",
    #                       parameterType=type))
    #         self.parameters.append(
    #             parameter('Optimal To {}'.format(i), "opti_to{}".format(i),
    #                       "GPDouble",
    #                       parameterType=type))
    #         self.parameters.append(
    #             parameter('Max Value {}'.format(i), "max_val{}".format(i),
    #                       "GPDouble",
    #                       parameterType=type))
    #         self.parameters.append(
    #             parameter('Combine {}'.format(i), "combine{}".format(i),
    #                       "GPString",
    #                       parameterType=type))
    #
    #     self.parameters.append(
    #         parameter("Output extent", "out_extent", "Feature Layer",
    #                   parameterType='Optional'
    #                   ))
    #     self.parameters.append(
    #         parameter("Output raster", "out_raster", 'Raster dataset',
    #                   parameterType='Derived', direction='Output'
    #                   ))
    #     self.parameters.append(
    #         parameter('E-mails', 'emails', "GPString",
    #                   parameterType='Optional'))

    def getParameterInfo(self):
        """Define parameter definitions"""

        for i in range(1, 11):
            if i == 1:
                type = 'Required'
            else:
                type = 'Optional'
            self.parameters.append(
                parameter('Raster Layer {}'.format(i), "in_raster{}".format(i),
                          "Raster Layer",
                          parameterType=type))
            self.parameters.append(
                parameter('Min Value {}'.format(i), "min_val{}".format(i),
                          "GPDouble",
                          parameterType=type))
            self.parameters.append(
                parameter('Optimal From {}'.format(i), "opti_from{}".format(i),
                          "GPDouble",
                          parameterType=type))
            self.parameters.append(
                parameter('Optimal To {}'.format(i), "opti_to{}".format(i),
                          "GPDouble",
                          parameterType=type))
            self.parameters.append(
                parameter('Max Value {}'.format(i), "max_val{}".format(i),
                          "GPDouble",
                          parameterType=type))
            self.parameters.append(
                parameter('Combine {}'.format(i), "combine{}".format(i),
                          "GPString",
                          parameterType=type))

        self.parameters.append(
            parameter("Output extent", "out_extent", "Feature Layer",
                      parameterType='Optional'
                      ))
        self.parameters.append(
            parameter("Output raster", "out_raster", 'Raster dataset',
                      parameterType='Derived', direction='Output'
                      ))
        self.parameters.append(
            parameter('E-mails', 'emails', "GPString",
                      parameterType='Optional')
        )

        for i, param in enumerate(self.parameters):
            if i in [5, 11, 17, 23, 29, 35, 41, 47, 53, 59]:
                if param.value != '' or param.value != "#":
                    self.parameters[i].filter.type = 'ValueList'

                    self.parameters[i].filter.list = ['Yes', 'No']
        return self.parameters

    def isLicensed(self):
        """ Set whether tool is licensed to execute."""
        # Check availability of Spatial Analyst
        spatialAnalystCheckedOut = super(LandSuitability, self).isLicensed()
        return spatialAnalystCheckedOut

    def updateParameters(self, parameters):
        """ Modify the values and properties of parameters before internal
            validation is performed.  This method is called whenever a parameter
            has been changed.
            Args:
                parameters: Parameters from the tool.
            Returns: Parameter values.
        """

        in_raster = self.prepare_value_table(parameters)
        for key, j in enumerate([0, 6, 12, 18, 24, 30, 36, 42, 48, 54]):
            if key == len(in_raster):
                break
            if parameters[j].value and parameters[j].altered:
                paramInRaster = super(LandSuitability,
                                      self).calculateStatistics(
                    parameters[j].valueAsText.replace("\\", "/").
                        replace("'", "")
                )
                if paramInRaster is not None:
                    # Minimum raster value
                    parameters[j + 1].value = paramInRaster.minimum
                    # Maximum raster value
                    parameters[j + 4].value = paramInRaster.maximum
                    # in_raster = parameters[0]
                    # Raster from the value table

                    # Number of value table columns
                    # vtab = arcpy.ValueTable(len(in_raster.columns))
                    # vtab = self.value_table_cols
                    # ras_max_min = True
                    # # Get values from the generator function and update value table
                    # for ras_file, minVal, maxVal, opt_from_val, opt_to_val, \
                    #     ras_combine, row_count in self.getRowValue(
                    #     in_raster, ras_max_min
                    # ):
                    #     minVal.setValue(minVal)
                    #     maxVal.setValue(maxVal)
                    #     # Check if there is space in file path
                    #     if " " in ras_file.valueAsText:
                    #         ras_file = "'" + ras_file + "'"
                    # self.updateValueTable(
                    #     in_raster, opt_from_val, opt_to_val, ras_combine, vtab,
                    #     ras_file, minVal, maxVal
                    # )

    def updateValueTable(self, in_raster, opt_from_val, opt_to_val,
                         ras_combine, vtab, ras_file, minVal, maxVal):
        """ Update value parameters in the tool.
            Args:
                in_raster: Raster inputs
                opt_from_val: Optimal From value
                opt_to_val: Optimal To value
                ras_combine: Combine value
                vtab: Number of value table columns
                ras_file: Raster file path
                minVal: Minimum raster data value
                maxVal: Maximum raster data value
            Returns: Updated value table values.
        """
        # End of value table, now update value table last row with new column data
        if opt_from_val == "#" and opt_to_val == "#" and ras_combine == "#":
            vtab.addRow(
                '{0} {1} {2} {3} {4} {5}'.format(ras_file, minVal, "#", "#",
                                                 maxVal, "#"))
            in_raster.value = vtab.exportToString()

        elif opt_from_val != "#" and opt_to_val == "#" and ras_combine == "#":
            vtab.addRow('{0} {1} {2} {3} {4} {5}'.format(ras_file, minVal,
                                                         opt_from_val, "#",
                                                         maxVal, "#"))
            in_raster.value = vtab.exportToString()
        elif opt_from_val == "#" and opt_to_val != "#" and ras_combine == "#":
            vtab.addRow('{0} {1} {2} {3} {4} {5}'.format(ras_file, minVal, "#",
                                                         opt_to_val, maxVal,
                                                         "#"))
            in_raster.value = vtab.exportToString()
        elif opt_from_val == "#" and opt_to_val == "#" and ras_combine != "#":
            vtab.addRow(
                '{0} {1} {2} {3} {4} {5}'.format(ras_file, minVal, "#", "#",
                                                 maxVal, ras_combine))
            in_raster.value = vtab.exportToString()
        elif opt_from_val != "#" and opt_to_val != "#" and ras_combine == "#":
            vtab.addRow('{0} {1} {2} {3} {4} {5}'.format(ras_file, minVal,
                                                         opt_from_val,
                                                         opt_to_val, maxVal,
                                                         "#"))
            in_raster.value = vtab.exportToString()
        elif opt_from_val == "#" and opt_to_val != "#" and ras_combine != "#":
            vtab.addRow('{0} {1} {2} {3} {4} {5}'.format(ras_file, minVal, "#",
                                                         opt_to_val, maxVal,
                                                         ras_combine))
            in_raster.value = vtab.exportToString()
        elif opt_from_val != "#" and opt_to_val == "#" and ras_combine != "#":
            vtab.addRow('{0} {1} {2} {3} {4} {5}'.format(ras_file, minVal,
                                                         opt_from_val, "#",
                                                         maxVal, ras_combine))
            in_raster.value = vtab.exportToString()
        elif opt_from_val != "#" and opt_to_val != "#" and ras_combine != "#":
            vtab.addRow('{0} {1} {2} {3} {4} {5}'.format(ras_file, minVal,
                                                         opt_from_val,
                                                         opt_to_val, maxVal,
                                                         ras_combine))
            in_raster.value = vtab.exportToString()

    def get_value_table_count(self, parameters):

        count = 0
        for i in [0, 6, 12, 18, 24, 30, 36, 42, 48, 54]:

            if isinstance(parameters[i].valueAsText, unicode):
                count = count + 1
        return count

    def prepare_value_table(self, parameters):
        row_count = self.get_value_table_count(parameters)
        column_count = self.value_table_cols
        value_table = []
        for row in range(0, row_count):

            column = []
            for col in range(row * column_count,
                             column_count + row * column_count):
                param = parameters[col]
                column.append(param)
            value_table.append(column)
        return value_table

    def updateMessages(self, parameters):
        """ Modify the messages created by internal validation for each tool
            parameter. This method is called after internal validation.
            Args:
                parameters: Parameters from the tool.
            Returns: Internal validation messages.
        """
        if parameters[0].value:
            prev_input = ""
            ras_ref = []
            all_ras_ref = []
            # in_raster = parameters[0]

            in_raster = self.prepare_value_table(parameters)

            if parameters[0].altered:
                # The number of rows in the table
                # num_rows = len(in_raster.values)
                num_rows = self.get_value_table_count(parameters)
                ras_max_min = True
                prev_ras_val = []
                i = 0

                # Get values from the generator function to show update messages
                for ras_file, minVal, maxVal, opt_from_val, opt_to_val, \
                    ras_combine, row_count in self.getRowValue(in_raster,
                                                               ras_max_min):
                    i += 1
                    # Set input raster duplicate warning
                    if len(prev_ras_val) > 0:
                        # Set duplicate input warning
                        super(LandSuitability, self).uniqueValueValidator(
                            prev_ras_val, ras_file, parameters[0],
                            field_id=False
                        )
                        prev_ras_val.append(ras_file)
                    else:
                        prev_ras_val.append(ras_file)
                    # Get spatial reference for all input raster
                    spatial_ref = arcpy.Describe(ras_file).SpatialReference

                    all_ras_ref.append(spatial_ref)
                    # Set raster spatial reference errors
                    if i == num_rows:
                        # Set raster spatial warning
                        super(LandSuitability, self).setRasSpatialWarning(
                            ras_file, ras_ref, in_raster, prev_input
                        )
                    else:
                        # Get spatial reference of rasters in value table
                        spatial_ref = arcpy.Describe(ras_file).SpatialReference
                        ras_ref.append(spatial_ref)
                    # Set errors for other value table variables
                    if opt_from_val.valueAsText == "#":
                        opt_from_val.setErrorMessage(
                            "Crop \"Optimal From\" value is missing")
                        opt_from_val = 0
                    if opt_to_val.valueAsText == "#":
                        opt_to_val.setErrorMessage(
                            "Crop \"Optimal To\" value is missing")
                    if ras_combine == "#":
                        ras_combine.setErrorMessage(
                            "Layer \"Combine\" value is missing")
                    if opt_to_val.valueAsText == "#" and \
                                    opt_from_val.valueAsText == "#" and \
                                    ras_combine == "#":
                        opt_from_val.setErrorMessage(
                            "Crop \"Optimal From\" value is missing")
                        opt_to_val.setErrorMessage(
                            "Crop \"Optimal To\" value is missing")
                        ras_combine.setErrorMessage(
                            "Layer \"Combine\" value is missing")
                    # if opt_from_val < minVal:
                    #     opt_from_val.setWarningMessage(
                    #         "Crop optimal value {0} is less than the minimum value {1}".format(
                    #             opt_from_val.valueAsText, minVal.valueAsText))
                    # elif opt_from_val > maxVal:
                    #     opt_from_val.setErrorMessage(
                    #         "Crop optimal value {0} is greater than the maximum value {1}".format(
                    #             opt_from_val.valueAsText, maxVal.valueAsText))
                    # elif opt_from_val > opt_to_val:
                    #     opt_from_val.setErrorMessage(
                    #         "Crop optimal value \"from\" is greater than crop optimal value \"to\"")
                    # elif opt_to_val < minVal:
                    #     opt_to_val.setErrorMessage(
                    #         "Crop optimal value {0} is less than the minimum value {1}".format(
                    #             opt_to_val, minVal))
                    # elif opt_to_val > maxVal:
                    #     opt_to_val.setWarningMessage(
                    #         "Crop optimal value {0} is greater than the maximum value {1}".format(
                    #             opt_to_val.valueAsText, maxVal.valueAsText))
                    # elif ras_combine.lower() != "yes":
                    #     if ras_combine.lower() != "no":
                    #         ras_combine.setErrorMessage(
                    #             "Layer \"Combine\" field expects \"Yes\" or \"No\" input value")
                    elif row_count == 0 and ras_combine.lower() != "no":
                        ras_combine.setErrorMessage(
                            "The first \"Combine\" value should ONLY be \"No\"")
                    elif num_rows == 1:
                        ras_file.setWarningMessage(
                            "One raster in place. Two are recommended")
            # Set feature class spatial reference errors
            if parameters[60].value is not None and parameters[60].altered:
                # Set feature class spatial warning
                if arcpy.Exists(parameters[60].value):
                    super(LandSuitability, self).setFcSpatialWarning(
                        parameters[60], all_ras_ref[-1], prev_input
                    )
                    # # Set ESRI grid output file size error
                    # super(LandSuitability, self).setFileNameLenError(
                    #     parameters[61])
                    # return

    def output_name(self, value_table):
        names = []
        for row in value_table:
            names.append(ntpath.basename(row[0].valueAsText)[0:3])
        name = '_'.join(names)
        name = '{}.tif'.format(name)
        return name

    def execute(self, parameters, messages):
        """ Execute functions to process input raster.
            Args:
                parameters: Parameters from the tool.
                messages: Internal validation messages
            Returns: Land suitability raster.
        """
        try:
            i = 0
            ras_max_min = True
            # in_raster = parameters[0]
            # The number of rows in the table
            in_raster = self.prepare_value_table(parameters)

            num_rows = self.get_value_table_count(parameters)
            # num_rows = len(parameters[0].values)
            # Get output file path
            # out_ras = parameters[61].valueAsText.replace("\\", "/")
            out_ras = self.output_name(in_raster)
            # ras_temp_path = ntpath.dirname(out_ras)  # Get path without file name
            scratch_path = arcpy.env.scratchFolder.replace("\\", "/")

            ras_temp_path = scratch_path + "/Temp/"
            out_ras_path = '{}/{}'.format(ras_temp_path, out_ras)

            if not os.path.exists(ras_temp_path):
                os.makedirs(ras_temp_path)  # Create new directory
            if parameters[60].value is not None:
                if arcpy.Exists(parameters[60].value):
                    # Raster minus operation
                    in_fc = \
                        super(LandSuitability, self).getInputFc(
                            parameters[60])[
                            "in_fc"]
                    extent = arcpy.Describe(
                        in_fc).extent  # Get feature class extent
                    # Minus init operation

                    self.rasterMinusInit(
                        in_raster, ras_max_min, ras_temp_path, in_fc, extent
                    )
                else:
                    self.rasterMinusInit(in_raster, ras_max_min, ras_temp_path,
                                         in_fc=None, extent=None)
            else:
                self.rasterMinusInit(in_raster, ras_max_min, ras_temp_path,
                                     in_fc=None, extent=None)
            # Initialize raster condition operation
            self.rasterConditionInit(num_rows, "ras_min1_", "ras_min2_",
                                     "ras_max1_", "ras_max2_", ras_temp_path,
                                     "< ", "0")

            # Raster divide operation
            for ras_file, minVal, maxVal, opt_from_val, opt_to_val, \
                ras_combine, row_count in self.getRowValue(
                in_raster, ras_max_min):
                i += 1

                self.rasterDivide(opt_from_val.valueAsText, minVal.value,
                                  "ras_min2_" + str(i),
                                  "ras_min3_" + str(i), ras_temp_path,
                                  min_ras=True)
                self.rasterDivide(opt_to_val.valueAsText, maxVal.value,
                                  "ras_max2_" + str(i),
                                  "ras_max3_" + str(i), ras_temp_path,
                                  min_ras=False)
                if i == 1:
                    self.spatial_ref = arcpy.Describe(
                        ras_file).SpatialReference

            self.rasterConditionInit(num_rows, "ras_min3_", "ras_min4_",
                                     "ras_max3_", "ras_max4_", ras_temp_path,
                                     "> ",
                                     "1")  # Initialize raster condition operation

            # Calculate minimum rasters from the minimums and maximums calculation outputs
            for j in range(0, num_rows):
                j += 1
                arcpy.AddMessage(
                    "Generating minimum values for {0} and {1}\n".format(
                        "ras_min4_" + str(j), "ras_max4_" + str(j)))
                arcpy.gp.CellStatistics_sa(ras_temp_path + "ras_min4_" + str(
                    j) + ";" + ras_temp_path + "ras_max4_" + str(j),
                                           ras_temp_path + "ras_MnMx_" + str(
                                               j), "MINIMUM", "DATA")

                # Delete file
                super(LandSuitability, self).deleteFile(ras_temp_path,
                                                        "ras_min4_" + str(j),
                                                        "ras_max4_" + str(j))
            # Build a list with lists of temporary raster files
            ras_temp_file = self.setCombineFile(in_raster, ras_temp_path)
            out_ras_temp = 1  # Initial temporary raster value
            n = 0
            n_ras = 0  # Number of rasters for geometric mean calculation

            # Overlay minimum rasters to create a suitability raster/map
            # value_table_count = self.get_value_table_count(parameters)

            for item in ras_temp_file:

                if len(item) > 1:
                    n += 1

                    if u'yes' in item:
                        item.remove(u'yes')
                    if u'no' in item:
                        item.remove(u'no')
                    # if n <= value_table_count:
                    arcpy.AddMessage(
                        "Generating maximum values from "
                        "minimum values raster files \n"
                    )

                    arcpy.gp.CellStatistics_sa(
                        item, ras_temp_path + "rs_MxStat_" + str(n),
                        "MAXIMUM", "DATA"
                    )

                else:
                    for f in item:
                        n_ras += 1
                        arcpy.AddMessage(
                            "Multiplying file {0} with input raster \n".format(
                                ntpath.basename(f)))
                        out_ras_temp = out_ras_temp * arcpy.Raster(f)

            if arcpy.Exists(out_ras_temp):
                arcpy.AddMessage("Saving Temporary Output \n")
                out_ras_temp.save(ras_temp_path + "rs_TxTemp")
                # Initial temporary raster file for the next calculation
                out_ras_temp = arcpy.Raster(ras_temp_path + "rs_TxTemp")

            if n >= 1:
                # Get times temp file and multiply with maximum value
                # statistics output saved in a temporary directory
                for j in range(0, n):
                    n_ras += 1
                    j += 1
                    arcpy.AddMessage(
                        "Multiplying file {0} with input raster rs_MxStat_{1} \n".format(
                            os.path.basename(str(out_ras_temp)), str(j)))
                    out_ras_temp = out_ras_temp * arcpy.Raster(
                        ras_temp_path + "rs_MxStat_" + str(j))

            arcpy.AddMessage("Generating suitability output \n")
            # Calculate geometric mean
            out_ras_temp = out_ras_temp ** (1 / float(n_ras))
            arcpy.AddMessage("Saving suitability output\n")
            out_ras_temp.save(out_ras_path)
            arcpy.AddMessage("Suitability output saved! \n")
            arcpy.AddMessage("Creating data input log \n")
            # create parameters log file
            self.createParametersLog(out_ras_path, ras_max_min, in_raster)
            arcpy.AddMessage("Deleting temporary folder \n")

            output_path = '{}/{}'.format(scratch_path, out_ras)
            shutil.copy(out_ras_path, output_path)
            # shutil.rmtree(ras_temp_path)  # Delete folder
            # Load output to current MXD
            arcpy.DefineProjection_management(
                output_path,
                self.spatial_ref
            )
            # output_ras = arcpy.Raster(output_path)

            arcpy.SetParameterAsText(61, output_path)
            self.submit_message(output_path, parameters[62].value,
                                self.label)

        except Exception as ex:
            tb = sys.exc_info()[2]
            # tbinfo = traceback.format_tb(tb)[0]
            # pymsg = "PYTHON ERRORS:\nTraceback info:\n" + tbinfo + "\nError Info:\n" + str(sys.exc_info()[1])
            msgs = "ArcPy ERRORS:\n" + arcpy.GetMessages(2) + "\n"
            arcpy.AddError(''.join(traceback.format_tb(tb)))
            # arcpy.AddError(pymsg)
            arcpy.AddError(msgs)
            arcpy.AddMessage('ERROR: {0} \n'.format(ex))

            # super(LandSuitability, self).loadOutput(output_path)
            # arcpy.RefreshCatalog(ntpath.dirname(output_path))  # Refresh folder

    def rasterMinusInit(self, in_raster, ras_max_min, ras_temp_path, in_fc,
                        extent):
        """ Initializes raster minus operation
            Args:
                in_raster: Value table parameter with rows accompanied by columns.
                ras_max_min: A parameter that determines whether minimum
                and maximum value should be calculated or not.
                ras_temp_path: Temporary directory path.
                in_fc: Zone feature class input.
                extent: Zone feature class extent.
            Return: None
        """
        i = 0
        for ras_file, minVal, maxVal, opt_from_val, \
            opt_to_val, ras_combine, row_count in self.getRowValue(
            in_raster, ras_max_min):
            i += 1
            if extent is not None:
                # Raster clip operation
                arcpy.AddMessage(
                    "Clipping {0} \n".format(
                        ntpath.basename(ras_file.valueAsText)))
                arcpy.Clip_management(ras_file.valueAsText,
                                      "{0} {1} {2} {3}".format(extent.XMin,
                                                               extent.YMin,
                                                               extent.XMax,
                                                               extent.YMax),
                                      ras_temp_path + "ras_mask1_" + str(i),
                                      in_fc, "#", "ClippingGeometry")
                # Masked raster minus operation
                self.rasterMinus(
                    ras_temp_path + "ras_mask1_" + str(i), minVal,
                    "ras_min1_" + str(i), ras_temp_path, min_ras=True
                )
                self.rasterMinus(
                    ras_temp_path + "ras_mask1_" + str(i), maxVal,
                    "ras_max1_" + str(i), ras_temp_path, min_ras=False
                )
                # Delete temporary raster files
                super(LandSuitability, self).deleteFile(
                    ras_temp_path, "ras_mask1_" + str(i))
            else:
                # Raster minus operation
                self.rasterMinus(ras_file.valueAsText, minVal,
                                 "ras_min1_" + str(i),
                                 ras_temp_path, min_ras=True)
                self.rasterMinus(ras_file.valueAsText, maxVal,
                                 "ras_max1_" + str(i),
                                 ras_temp_path, min_ras=False)

    def rasterMinus(self, ras_file, val, ras_output, ras_temp_path, min_ras):
        """ Handles raster minus operation
            Args:
                ras_file: Input raster file
                val: Minimum and maximum value
                ras_output: Raster file output
                ras_temp_path: Temporary directory path
                min_ras: Boolean to determine if minimum value is available or not
            Return: Raster layer output
        """
        if min_ras:
            arcpy.AddMessage(
                "Calculating {0} - {1} \n".format(ntpath.basename(ras_file),
                                                  val.valueAsText))
            arcpy.gp.Minus_sa(ras_file, val.valueAsText,
                              ras_temp_path + ras_output)
        else:
            arcpy.AddMessage("Calculating {0} - {1} \n".format(val.valueAsText,
                                                               ntpath.basename(
                                                                   ras_file)))
            arcpy.gp.Minus_sa(val.valueAsText, ras_file,
                              ras_temp_path + ras_output)

    def rasterConditionInit(
            self, num_rows, ras_min_input, ras_min_output, ras_max_input,
            ras_max_output, ras_temp_path, comp_oper, comp_val
    ):
        """ Initializes raster condition operation
            Args:
                num_rows: Number of rows in the value table
                ras_min_input: Raster file input
                ras_min_output: Raster file output
                ras_max_input: Raster file input
                ras_max_output: Raster file output
                ras_temp_path: Temporary directory path
                comp_oper: Comparison operator
                comp_val: Comparison value
            Return:
                None
        """
        for j in range(0, num_rows):
            j += 1
            self.rasterCondition(ras_min_input + str(j),
                                 ras_min_output + str(j),
                                 ras_temp_path, comp_oper, comp_val)
            self.rasterCondition(ras_max_input + str(j),
                                 ras_max_output + str(j),
                                 ras_temp_path, comp_oper, comp_val)

    def rasterCondition(self, ras_input, ras_output, ras_temp_path, comp_oper,
                        comp_val):
        """ Handles raster condition operation
            Args:
                ras_input: Raster file input
                ras_output: Raster file output
                ras_temp_path: Temporary directory path
                comp_oper: Comparison operator
                comp_val: Comparison value

            Return:
                Raster layer output
        """
        arcpy.AddMessage(
            "Creating conditional output for {0} \n".format(ras_input)
        )
        arcpy.gp.Con_sa(ras_temp_path + ras_input, comp_val,
                        ras_temp_path + ras_output, ras_temp_path + ras_input,
                        "\"Value\" " + comp_oper + comp_val)
        # Delete temporary raster files
        super(LandSuitability, self).deleteFile(ras_temp_path, ras_input)

    def rasterDivide(self, opt_val, m_val, ras_input, ras_output,
                     ras_temp_path, min_ras):
        """ Handles raster divide operation
            Args:
                opt_val: Optimal From or Optimal To value
                m_val: Maximum or minimum value
                ras_input: Input raster file
                ras_output: Raster file output
                ras_temp_path: Temporary directory path
                min_ras: Boolean to determine if minimum value is available or not
            Return:
                Raster layer output
        """
        msg_ras_input = os.path.basename(ras_input)
        msg_ras_output = os.path.basename(ras_output)
        msg_ras_temp_path = os.path.basename(ras_temp_path)
        arcpy.AddMessage(
            "Calculating {0}; {1}; {2}; {3}; {4}; {5}\n".format(opt_val, m_val,
                                                                msg_ras_input,
                                                                msg_ras_output,
                                                                msg_ras_temp_path,
                                                                min_ras))
        if min_ras:
            if float(opt_val) - float(m_val) == 0:
                arcpy.AddMessage(
                    "Calculating {0} / {1} \n".format(msg_ras_input, "1"))
                arcpy.gp.Divide_sa(ras_temp_path + ras_input, "1",
                                   ras_temp_path + ras_output)
            else:
                arcpy.AddMessage(
                    "Calculating {0} / {1} - {2} \n".format(msg_ras_input,
                                                            opt_val,
                                                            m_val))
                arcpy.gp.Divide_sa(ras_temp_path + ras_input,
                                   str(float(opt_val) - float(m_val)),
                                   ras_temp_path + ras_output)
        else:
            if float(m_val) - float(opt_val) == 0:
                arcpy.AddMessage(
                    "Calculating {0} / {1} \n".format(msg_ras_input, "1"))
                arcpy.gp.Divide_sa(ras_temp_path + ras_input, "1",
                                   ras_temp_path + ras_output)
            else:
                arcpy.AddMessage(
                    "Calculating {0} / {1} - {2} \n".format(msg_ras_input,
                                                            m_val,
                                                            opt_val))
                arcpy.gp.Divide_sa(ras_temp_path + ras_input,
                                   str(float(m_val) - float(opt_val)),
                                   ras_temp_path + ras_output)
        super(LandSuitability, self).deleteFile(ras_temp_path, ras_input)

    def setCombineFile(self, in_raster, ras_temp_path):
        """ Build a list with lists of temporary raster files
            Args:
                in_raster: Value table parameter with rows accompanied by columns.
                ras_temp_path: Temporary directory path
            Returns:
                ras_file_lists: List with lists of temporary raster
        """
        # Splits lists of combine column value "no"
        ras_file_lists = self.splitCombineValue(in_raster)

        j = 0
        for i, item in enumerate(ras_file_lists):
            for k, val in enumerate(item):
                j += 1
                if j <= len(in_raster):
                    # Update lists with temporary files
                    ras_file_lists[i][k] = ras_temp_path + "ras_MnMx_" + str(j)
        return ras_file_lists

    def splitCombineValue(self, in_raster):
        """ Splits lists of combine column value "no" into individual lists.
            Args:
                in_raster: Value table parameter with rows accompanied by columns.
            Returns:
                split_combine_val: Group combine values with "no" lists split into
                individual lists
        """
        # Gets grouped combine values
        combine_val = self.getCombineValue(in_raster)

        split_combine_val = []
        for item in combine_val:
            if len(item) > 1 and item[len(item) - 1] == "no":
                for val in item:  # Add list elements "no" as individual list
                    split_combine_val.append([val])
            else:
                split_combine_val.append(item)
        return split_combine_val

    def getCombineValue(self, in_raster):
        """ Gets combine column values and groups them in a list of lists.
            Args:
                in_raster: Value table parameter with rows accompanied by columns.
            Returns:
                in_list: Grouped elements in list of lists
        """
        ras_max_min = False
        combine_val = []
        # Get combine column values
        for ras_combine in self.getRowValue(in_raster, ras_max_min):
            combine_val.append(ras_combine.valueAsText.lower())
            # Group combine elements
        # arcpy.AddMessage('print combine_val {}'.format(combine_val))
        in_list = [list(g) for k, g in groupby(combine_val)]
        # arcpy.AddMessage('print in_list {}'.format(in_list))
        for i, item in enumerate(in_list):
            if len(in_list) > 1:
                if len(item) == 1 and item[0] == "no":
                    if i != len(in_list) - 1:  # Exclude last element
                        del in_list[i]  # Delete list
                        # Insert deleted element to the next list
                        in_list[i].insert(0, "no")
                elif len(item) > 1 and item[0] == "no":
                    in_list[i].pop()  # Remove the last element
                elif item[0] == "yes":
                    in_list[i].insert(0, "no")  # Insert popped element
        return in_list

    def getRowValue(self, in_raster, ras_max_min):
        """ Gets row values and calculate raster maximum and minimum values.
            Args:
                in_raster: Value table parameter with rows accompanied by columns.
                ras_max_min: A parameter that determines whether minimum and maximum value should be calculated or not.
            Returns:
                Optimal From, Optimal To, raster file path, raster minimum value and maximum value
        """
        for i, lst in enumerate(in_raster):  # .valueAsText.split(";")):
            row_count = i
            # Clean value table data
            # lst_val = super(LandSuitability, self).formatValueTableData(lst)
            lst_val = lst
            ras_file = lst_val[0]  # Get raster file path
            # ras_file = ras_file.replace("\\", "/")
            minVal = lst_val[1]  # Minimum raster value
            opt_from_val = lst_val[2]  # Get crop optimum value from
            opt_to_val = lst_val[3]  # Get crop optimum value to
            maxVal = lst_val[4]  # Maximum raster value
            ras_combine = lst_val[5]  # Get combine option

            if ras_max_min:
                if minVal == "#" or maxVal == "#" or ras_combine == "#":
                    paramInRaster = super(LandSuitability,
                                          self).calculateStatistics(
                        ras_file.replace("\\", "/").replace("'", ""))
                    minVal.value = paramInRaster.minimum  # Minimum raster value
                    maxVal.value = paramInRaster.maximum  # Maximum raster value
                    ras_combine = "No"
                    yield ras_file, minVal, maxVal, opt_from_val, opt_to_val, ras_combine, row_count  # Return output
                else:
                    if row_count == 0:  # Set first row to "No"
                        ras_combine = "No"
                        yield ras_file, minVal, maxVal, opt_from_val, opt_to_val, ras_combine, row_count
                    else:
                        yield ras_file, minVal, maxVal, opt_from_val, opt_to_val, ras_combine, row_count
            else:
                yield ras_combine

    def createParametersLog(self, out_ras, ras_max_min, in_raster):
        """ Loads output to the current MXD
            Args:
                out_ras: Land suitability layer file path
                ras_max_min: A parameter that determines whether minimum and
                maximum value should be calculated or not.
                in_raster: Value table parameter with rows accompanied by columns.
            Return: None
        """
        out_ras_path = ntpath.dirname(out_ras)  # Get path without file name
        out_log_txt = out_ras_path + "/data_log.txt"
        t = time.localtime()
        local_time = time.asctime(t)
        with open(out_log_txt, "w") as f:
            f.write(local_time + " Tool Inputs\n")
            f.write("\n")
            for ras_file, minVal, maxVal, opt_from_val, \
                opt_to_val, ras_combine, row_count in self.getRowValue(
                in_raster, ras_max_min):
                new_line = '{}: {} ; {} ; {} ; {} ; {} ; {}'.format(
                    row_count, ras_file, minVal.valueAsText,
                    opt_from_val.valueAsText, maxVal.valueAsText,
                    opt_to_val.valueAsText, ras_combine
                )
                # new_line = str(row_count) + ": " + ras_file.valueAsText + " ; " + minVal.valueAsText + \
                #            " ; " + opt_from_val.valueAsText + " ; " + maxVal.valueAsText + " ; " + \
                #            opt_to_val.valueAsText + " ; " + ras_combine.valueAsText
                f.write(new_line + "\n")

    def createFcLayer(self, out_fc):
        """ Handles creation of feature class layer
            Args:
                parameters: Tool parameters object
                out_fc: Output feature class parameter
            Return:
                lyr: Feature class layer
        """
        if out_fc[-4:] != ".shp":
            out_fc = out_fc + ".shp"
        return arcpy.mapping.Layer(out_fc)



class LandSimilarity(TargetingTool):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Land Similarity"
        self.description = ""
        self.spatial_ref = None
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define parameter definitions"""
        self.parameters = [
            parameter("Input raster", "in_raster", "Raster Layer",
                      multiValue=True),
            parameter("Input point layer", "in_point", "Feature Layer"),
            parameter("Output extent", "out_extent", "Feature Layer",
                      parameterType='Optional'),
            parameter("R executable", "r_exe", "File"),
            parameter(
                "Output Mahalanobis raster", "out_raster_mnobis",
                'Raster dataset', parameterType='Derived', direction='Output'
            ),
            parameter(
                "Output MESS raster", "out_raster_mess", 'Raster dataset',
                parameterType='Derived', direction='Output'
            ),

            parameter(
                'E-mails', 'emails', "GPString",
                parameterType='Optional'
            )

        ]

        self.parameters[1].filter.list = ["Point"]  # Geometry type filter
        return self.parameters

    def isLicensed(self):
        """ Set whether tool is licensed to execute."""
        # Check availability of Spatial Analyst
        spatialAnalystCheckedOut = super(LandSimilarity,
                                         self).isLicensed()
        return spatialAnalystCheckedOut

    def updateParameters(self, parameters):
        """ Modify the values and properties of parameters before internal
            validation is performed.  This method is called whenever a parameter
            has been changed.
            Args:
                parameters: Parameters from the tool.
            Returns: Parameter values.
        """
        if parameters[0].value:
            if not parameters[3].value:  # Set initial value
                root_dir = "C:/Program Files/R"
                if os.path.isdir(root_dir):
                    # Get R executable file
                    parameters[3].value = self.getRExecutable(root_dir)

        return

    def updateMessages(self, parameters):
        """ Modify the messages created by internal validation for each tool
            parameter.  This method is called after internal validation.
            Args:
                parameters: Parameters from the tool.
            Returns: Internal validation messages.
        """
        # output to the screen

        if parameters[0].value:
            prev_input = ""
            ras_ref = []
            all_ras_ref = []
            in_val_raster = parameters[0]
            if parameters[0].altered:
                num_rows = len(
                    in_val_raster.values)  # The number of rows in the table
                prev_ras_val = []
                i = 0
                # Get values from the generator function to show update messages
                for row_count, in_ras_file in self.getRasterFile(
                        in_val_raster):
                    i += 1
                    # Set input raster duplicate warning
                    if len(prev_ras_val) > 0:
                        super(LandSimilarity, self).uniqueValueValidator(
                            prev_ras_val, in_ras_file, parameters[0],
                            field_id=False)  # Set duplicate input warning
                        prev_ras_val.append(in_ras_file)
                    else:
                        prev_ras_val.append(in_ras_file)
                    # Get spatial reference for all input raster
                    spatial_ref = arcpy.Describe(in_ras_file).SpatialReference
                    all_ras_ref.append(spatial_ref)
                    # Set raster spatial reference errors
                    if i == num_rows:
                        super(LandSimilarity, self).setRasSpatialWarning(
                            in_ras_file, ras_ref, in_val_raster,
                            prev_input)  # Set raster spatial warning
                    else:
                        spatial_ref = arcpy.Describe(
                            in_ras_file).SpatialReference  # Get spatial reference of input rasters
                        ras_ref.append(spatial_ref)
            if parameters[1].value and parameters[1].altered:
                super(LandSimilarity, self).setFcSpatialWarning(parameters[1],
                                                                all_ras_ref[
                                                                    -1],
                                                                prev_input)  # Set feature class spatial warning
            if parameters[2].value and parameters[2].altered:
                super(LandSimilarity, self).setFcSpatialWarning(parameters[2],
                                                                all_ras_ref[
                                                                    -1],
                                                                prev_input)
        if parameters[1].value and parameters[1].altered:
            in_fc = parameters[1].valueAsText.replace("\\", "/")
            result = arcpy.GetCount_management(
                in_fc)  # Get number of features in the input feature class
            if int(result.getOutput(0)) <= 1:
                parameters[1].setWarningMessage(
                    "Input point layer has a single feature. MESS will NOT be calculated.")
        if parameters[3].value and parameters[3].altered:
            r_exe_path = parameters[3].valueAsText
            if not r_exe_path.endswith(("\\bin\\R.exe", "\\bin\\x64\\R.exe",
                                        "\\bin\\i386\\R.exe")):
                parameters[3].setErrorMessage(
                    "{0} is not a valid R executable".format(r_exe_path))
                # super(LandSimilarity, self).setDuplicateNameError(parameters[4],
                #                                                   parameters[
                #                                                       5])  # Set duplicate file name error
                # super(LandSimilarity, self).setDuplicateNameError(parameters[5],
                #                                                   parameters[4])
                # super(LandSimilarity, self).setFileNameLenError(
                #     parameters[4])  # Set ESRI grid output file size error
                # super(LandSimilarity, self).setFileNameLenError(parameters[5])
                # return

    def execute(self, parameters, messages):
        """ Execute functions to process input raster.
            Args:
                parameters: Parameters from the tool.
                messages: Internal validation messages
            Returns: Land suitability raster.
        """
        try:
            r_exe_path = parameters[3].valueAsText
            # out_mnobis_ras = parameters[4].valueAsText.replace("\\", "/")  # Get mahalanobis output
            # out_mess_ras = parameters[5].valueAsText.replace("\\", "/")  # Get mess output
            out_mnobis_ras = 'Mahalanobis_Raster.tif'
            out_mess_ras = 'MESS_Raster.tif'

            # ras_temp_path = ntpath.dirname(
            #     out_mnobis_ras)  # Get path without file name
            scratch_folder = arcpy.env.scratchFolder.replace("\\", "/")

            # os.path.join(arcpy.env.scratchFolder)
            ras_temp_path = scratch_folder + "/Temp/"

            out_mnobis_ras_path = ras_temp_path + out_mnobis_ras
            out_mess_ras_path = ras_temp_path + out_mess_ras
            # Create temporary directory if it doesn't exist
            if not os.path.exists(ras_temp_path):
                os.makedirs(ras_temp_path)
            # Copy point layer to temporary directory
            in_fc_pt = parameters[1].valueAsText.replace("\\", "/")

            # Copy dataset from source to destination
            if os.path.isfile(in_fc_pt):
                in_fc_pt = self.copyDataset(ras_temp_path, in_fc_pt, in_fc_pt)
            # else:
            #
            #     # # Get point layer data source
            #     in_fc_pt = super(LandSimilarity, self).getLayerDataSource(
            #         parameters[1]
            #     )
            #     in_fc_pt = self.copyDataset(ras_temp_path, in_fc_pt, in_fc_pt)

            # raster sample creation
            if parameters[2].value:
                in_fc = super(LandSimilarity, self).getInputFc(parameters[2])[
                    "in_fc"]
                extent = arcpy.Describe(
                    in_fc).extent  # Get feature class extent
                # Create raster cell value sample
                self.createValueSample(
                    parameters, in_fc_pt, ras_temp_path, in_fc, extent
                )
            else:
                self.createValueSample(parameters, in_fc_pt, ras_temp_path,
                                       in_fc=None,
                                       extent=None)  # Create raster cell value sample
            self.deleteTempFile(parameters,
                                ras_temp_path)  # Delete temporary files
            arcpy.AddMessage("Joining {0} to {1} \n".format(
                os.path.basename(in_fc_pt),
                os.path.basename(ras_temp_path) + "temp.dbf"
            )
            )
            arcpy.JoinField_management(
                in_fc_pt, "FID", ras_temp_path + "temp.dbf", "OID", ""
            )  # Join tables
            out_csv = ras_temp_path + "temp.csv"
            # Write feature class table to CSV file
            self.writeToCSV(in_fc_pt, out_csv)
            arcpy.management.Delete(in_fc_pt)  # Delete vector
            # Toolbox current working directory
            cwd = os.path.dirname(os.path.realpath(__file__))

            self.createRScript(parameters, ras_temp_path)  # Create R script
            # TODO apply this for desktop version
            self.runCommand(r_exe_path, ras_temp_path)  # Run R command
            # ASCII to raster conversion
            self.asciiToRasterConversion(
                parameters, ras_temp_path, out_mnobis_ras, out_mess_ras)

            # shutil.rmtree(ras_temp_path)  # Delete directory
            # TODO apply this for desktop version
            result_path = OrderedDict()
            if os.path.isfile(out_mnobis_ras_path):
                final_mnobis_path = '{}/{}'.format(scratch_folder,
                                                   out_mnobis_ras)
                arcpy.CopyRaster_management(out_mnobis_ras_path,
                                            final_mnobis_path,
                                            colormap_to_RGB=True)
                arcpy.SetParameterAsText(4, final_mnobis_path)
                result_path['Output Mahalanobis Raster'] = final_mnobis_path

            if os.path.isfile(out_mess_ras_path):
                final_mess_path = '{}/{}'.format(scratch_folder, out_mess_ras)
                arcpy.CopyRaster_management(out_mess_ras_path, final_mess_path,
                                            colormap_to_RGB=True)
                arcpy.SetParameterAsText(5, final_mess_path)
                result_path['Output MESS Raster'] = final_mess_path

            self.submit_message(result_path, parameters[6], self.label)
            # self.load_output_to_mxd(out_mess_ras_path, out_mnobis_ras_path)
            shutil.rmtree(ras_temp_path)  # Delete directory

        except Exception as ex:
            tb = sys.exc_info()[2]
            # tbinfo = traceback.format_tb(tb)[0]
            # pymsg = "PYTHON ERRORS:\nTraceback info:\n" + tbinfo + "\nError Info:\n" + str(sys.exc_info()[1])
            msgs = "ArcPy ERRORS:\n" + arcpy.GetMessages(2) + "\n"
            arcpy.AddError(''.join(traceback.format_tb(tb)))
            # arcpy.AddError(pymsg)
            arcpy.AddError(msgs)
            arcpy.AddMessage('ERROR: {0} \n'.format(ex))

    def load_output_to_mxd(self, out_mnobis_ras_path, out_mess_ras_path):
        ##TODO use this method for the Desktop version
        """
        Get raster and load to the current mxd
        :param out_mnobis_ras_path: Mahalanobis output path.
        :type out_mnobis_ras_path: String
        :param out_mess_ras_path: MESS output path.
        :type out_mess_ras_path: String
        :return:
        :rtype:
        """
        out_ras = ""
        if arcpy.Exists(out_mnobis_ras_path) and arcpy.Exists(
                out_mess_ras_path):
            # Define spatial reference system
            arcpy.DefineProjection_management(
                out_mnobis_ras_path, self.spatial_ref)
            arcpy.DefineProjection_management(
                out_mess_ras_path,
                self.spatial_ref
            )

            out_ras = [out_mnobis_ras_path, out_mess_ras_path]
        else:
            if arcpy.Exists(out_mnobis_ras_path):
                # Define spatial reference system
                arcpy.DefineProjection_management(
                    out_mnobis_ras_path, self.spatial_ref
                )
                out_ras = out_mnobis_ras_path

            elif arcpy.Exists(out_mess_ras_path):
                # Define spatial reference system
                arcpy.DefineProjection_management(
                    out_mess_ras_path,
                    self.spatial_ref
                )
                out_ras = out_mess_ras_path
        # Load output to current MXD
        super(LandSimilarity, self).loadOutput(out_ras)
        # Refresh folder
        arcpy.RefreshCatalog(
            ntpath.dirname(out_mnobis_ras_path)
        )

    def getRExecutable(self, root_dir):
        """ Get R executable file path
            Args:
                root_dir: Root directory
            Returns:
                r_exe_file: R executable file path
        """
        r_exe_file = ""
        if os.path.exists(root_dir):
            for root, dirs, files in os.walk("C:/Program Files/R"):
                for file_name in files:
                    if file_name == "R.exe":
                        r_exe_path = os.path.join(root, file_name).replace("/",
                                                                           "\\")
                        if r_exe_path.endswith("\\bin\\x64\\R.exe"):
                            r_exe_file = r_exe_path
        return r_exe_file

    def createValueSample(self, parameters, in_fc_pt, ras_temp_path, in_fc,
                          extent):
        """ Create raster cell value sample
            Args:
                parameters: Tool parameters
                in_fc_pt: Input point layer
                ras_temp_path: Temporary folder
                in_fc: Feature class input.
                extent: Feature class extent.
            Returns: None
        """
        in_val_raster = parameters[0]
        num_rows = len(in_val_raster.values)  # The number of rows in the table
        first_in_raster = ""
        sample_in_ras = []
        for row_count, in_ras_file in self.getRasterFile(in_val_raster):
            i = row_count + 1
            if extent is not None:
                arcpy.AddMessage(
                    "Clipping {0} \n".format(os.path.basename(in_ras_file))
                )
                arcpy.AddMessage(
                    "Grid length Path: {}, Filename: {}".format(
                        os.path.basename(in_ras_file),
                        os.path.basename(ras_temp_path) + "\\mask_" + str(i)
                    )
                )
                arcpy.Clip_management(
                    in_ras_file,
                    "{0} {1} {2} {3}".format(
                        extent.XMin,
                        extent.YMin,
                        extent.XMax,
                        extent.YMax
                    ),
                    ras_temp_path + "mask_" + str(i),
                    in_fc, "#", "ClippingGeometry"
                )

                if num_rows > 1:
                    if i == 1:
                        first_in_raster = ras_temp_path + "mask_" + str(i)
                in_ras_mask = ras_temp_path + "mask_" + str(i)
                # Convert raster to ASCII
                sample_ras = self.convertRasterToASCII(
                    num_rows, ras_temp_path,
                    i, first_in_raster,
                    in_ras_mask
                )

                sample_in_ras.append(sample_ras)
            else:
                if num_rows > 1:
                    if i == 1:
                        first_in_raster = in_ras_file
                sample_ras = self.convertRasterToASCII(num_rows, ras_temp_path,
                                                       i, first_in_raster,
                                                       in_ras_file)
                sample_in_ras.append(sample_ras)
        arcpy.AddMessage("Creating sample values \n")
        arcpy.gp.Sample_sa(sample_in_ras, in_fc_pt, ras_temp_path + "temp.dbf",
                           "NEAREST")  # Process: Sample

    def convertRasterToASCII(self, num_rows, ras_temp_path, i, first_in_raster,
                             in_raster):
        """ Converts raster to ASCII
            Args:
                num_rows: Number of input rasters
                ras_temp_path: Temporary folder
                i: Raster counter
                first_in_raster: First input raster
                in_raster: Raster with applied environment settings
            Returns:
                sample_ras: Raster to be used in creating a cell value sample table
        """
        if num_rows > 1:
            if i == 1:
                sample_ras = first_in_raster
                arcpy.AddMessage("Converting {0} to ASCII file {1} \n".format(
                    os.path.basename(first_in_raster),
                    os.path.basename(ras_temp_path) + "tempAscii_" + str(
                        i) + ".asc"))
                arcpy.RasterToASCII_conversion(
                    first_in_raster,
                    ras_temp_path + "tempAscii_" + str(i) + ".asc"
                )
            else:
                in_mem_raster = self.applyEnvironment(first_in_raster,
                                                      in_raster)
                in_mem_raster.save(ras_temp_path + "ras_envset_" + str(
                    i))  # Save memory raster to disk
                sample_ras = ras_temp_path + "ras_envset_" + str(i)
                arcpy.AddMessage("Converting {0} to ASCII file {1} \n".format(
                    os.path.basename(ras_temp_path) + "ras_envset_" + str(i),
                    os.path.basename(ras_temp_path) + "tempAscii_" + str(
                        i) + ".asc"))
                arcpy.RasterToASCII_conversion(
                    ras_temp_path + "ras_envset_" + str(i),
                    ras_temp_path + "tempAscii_" + str(i) + ".asc")
        else:
            sample_ras = in_raster
            arcpy.AddMessage(
                "Converting {0} to ASCII file {1} \n".format(
                    os.path.basename(in_raster),
                    os.path.basename(ras_temp_path) + "tempAscii_" + str(
                        i) + ".asc"
                )
            )
            arcpy.RasterToASCII_conversion(in_raster,
                                           ras_temp_path + "tempAscii_" + str(
                                               i) + ".asc")
        return sample_ras

    def applyEnvironment(self, first_in_raster, in_raster):
        """ Apply environment settings
            Args:
                first_in_raster: First input raster
                in_raster: Raster with applied environment settings
            Returns: None
        """
        arcpy.env.extent = first_in_raster
        arcpy.env.cellSize = first_in_raster
        arcpy.env.outputCoordinateSystem = first_in_raster
        arcpy.env.snapRaster = first_in_raster

        self.spatial_ref = self.get_srid_from_file(first_in_raster)

        arcpy.AddMessage(
            "Applying environment settings for {0}".format(
                os.path.basename(in_raster)))
        in_raster = arcpy.Raster(in_raster)
        return arcpy.sa.ApplyEnvironment(in_raster)

    def deleteTempFile(self, parameters, ras_temp_path):
        """ Delete temporary files
            Args:
                parameters: Tool parameters
                ras_temp_path: Temporary folder
            Returns: None
        """
        for i in xrange(1, len(parameters[0].values)):
            if arcpy.Exists(ras_temp_path + "mask_" + str(i)):
                super(LandSimilarity, self).deleteFile(ras_temp_path,
                                                       "mask_" + str(
                                                           i))  # Delete temporary files
            if arcpy.Exists(ras_temp_path + "ras_envset_" + str(i)):
                super(LandSimilarity, self).deleteFile(ras_temp_path,
                                                       "ras_envset_" + str(
                                                           i))  # Delete temporary files

    def writeToCSV(self, in_fc_pt, out_csv):
        """ Write feature class table to CSV file
            Args:
                in_fc_pt: Input point layer
                out_csv: Output CSV file
            Returns: None
        """
        # Get field names
        fields = arcpy.ListFields(in_fc_pt)
        field_names = [field.name for field in fields]
        arcpy.AddMessage(
            "Exporting {0} table to {1} \n".format(
                os.path.basename(in_fc_pt),
                os.path.basename(out_csv)
            )
        )
        with open(out_csv, 'wb') as f:
            w = csv.writer(f)
            w.writerow(field_names)  # Write field names to CSV file as headers
            # Search through rows and write values to CSV
            for row in arcpy.SearchCursor(in_fc_pt):
                field_vals = [row.getValue(field.name) for field in fields]
                w.writerow(field_vals)
            del row

    def createRScript(self, parameters, ras_temp_path):
        """ Create R script
            Args:
                parameters: Tool parameters
                ras_temp_path: Temporary folder
            Returns: None
        """
        i = 0
        in_val_raster = parameters[0]
        #  Get number of rasters
        for row_count, in_ras_file in self.getRasterFile(in_val_raster):
            row_count += 1
            i = row_count
        with open(ras_temp_path + 'out_script.r', 'w') as f:
            cwd = os.path.dirname(os.path.realpath(
                __file__))  # Toolbox current working directory
            # cwd = self.getDirectoryPath(cwd)  # Get subdirectory path
            # similar_script = self.getFilePath(cwd,
            #                                   "similarity_")  # Get script path
            # read_script = self.getFilePath(cwd, "readAscii")
            # write_script = self.getFilePath(cwd, "writeAscii")
            similar_script_rel = 'R_Scripts/similarity_analysis.r'
            read_script_rel = 'R_Scripts/readAscii.r'
            write_script_rel = 'R_Scripts/writeAscii.r'
            script_dir = os.path.dirname(__file__)

            similar_script = os.path.join(script_dir,
                                          similar_script_rel).replace("\\",
                                                                      "/")
            read_script = os.path.join(script_dir, read_script_rel).replace(
                "\\", "/")
            write_script = os.path.join(script_dir, write_script_rel).replace(
                "\\", "/")
            # Write out a script
            f.write(
                'source("' + similar_script + '"); similarityAnalysis(' + str(
                    i) + ',"' + read_script + '","' + write_script + '","' + ras_temp_path + '") \n')

    def getDirectoryPath(self, cwd):
        """ Get subdirectory path from the toolbox directory
            Args:
                cwd: Current toolbox directory
            Returns: Script subdirectory full path
        """
        for name in os.listdir(cwd):
            if os.path.isdir(os.path.join(cwd, name)):
                if name == "R_Scripts":
                    return os.path.join(cwd, name)

    def getFilePath(self, cwd, start_char):
        """ Get file path from the toolbox directory
            Args:
                cwd: Current script directory
                start_char: File name start character
            Returns: File full path
        """
        for f in os.listdir(cwd):
            if not os.path.isdir(os.path.join(cwd, f)):
                if f.startswith(start_char) and f.endswith(".r"):
                    return os.path.join(cwd, f).replace("\\", "/")

    def runCommand(self, r_exe_path, ras_temp_path):
        """ Run R command
            Args:
                r_exe_path: Executable R file
                ras_temp_path: Temporary folder
            Returns: None
        """
        r_cmd = '"' + r_exe_path + '" --vanilla --slave --file="' + ras_temp_path + 'out_script.r"'  # r command

        arcpy.AddMessage("Running similarity analysis \n")
        # TODO Apply this change on desktop version
        CREATE_NO_WINDOW = 0x08000000
        # Open shell and run R command
        # subprocess.call(shlex.split(r_cmd), shell=False,
        #                 creationflags=CREATE_NO_WINDOW)
        # result = subprocess.check_call(shlex.split(r_cmd), shell=False,
        #                 creationflags=CREATE_NO_WINDOW)
        process = subprocess.Popen(shlex.split(r_cmd), stdout=subprocess.PIPE,
                                   creationflags=CREATE_NO_WINDOW)
        process.wait()

        # arcpy.AddMessage("Print {}\n".format(process.stdout))

    def asciiToRasterConversion(
            self, parameters, ras_temp_path, out_mnobis_ras, out_mess_ras):
        """ ASCII to raster conversion
            Args:
                Parameters: Tool parameters
                ras_temp_path: Temporary folder
            Returns: None
        """
        r_exe_file = parameters[3].valueAsText.replace("\\",
                                                       "/")  # Get R.exe file path
        # out_mnobis_ras = parameters[4].valueAsText.replace("\\",
        #                                                    "/")  # Get mahalanobis output
        # out_mess_ras = parameters[5].valueAsText.replace("\\",
        #                                                  "/")  # Get mess output
        maha_ascii_path = ras_temp_path + "MahalanobisDist.asc"
        mess_ascii_path = ras_temp_path + "MESS.asc"
        out_mnobis_ras_path = ras_temp_path + out_mnobis_ras
        out_mess_ras_path = ras_temp_path + out_mess_ras

        r_version = r_exe_file.split("bin")[0]
        r_modEvA = r_version + "library/modEvA"
        arcpy.AddMessage('Print {}'.format(r_modEvA))
        if not os.path.isdir(r_modEvA):
            arcpy.AddError(
                'Error: {0} package missing.\n'.format(
                    os.path.basename(r_modEvA))
            )

        arcpy.AddMessage("ASCII conversion of {0} to raster {1} \n".format(
            os.path.basename(maha_ascii_path),
            os.path.basename(out_mnobis_ras_path)
        )
        )
        # dsc = gp.Describe(ascii_name)  # Gets the Description about the ascii file
        # maha_ascii_in = dsc.CatalogPath  # Gets the Full Catalog Path of the ascii file
        if os.path.isfile(maha_ascii_path):
            arcpy.ASCIIToRaster_conversion(
                maha_ascii_path, out_mnobis_ras_path, "INTEGER"
            )
        else:
            arcpy.AddMessage("MahalanobisDist.asc could not be found.  \n")
        if os.path.isfile(mess_ascii_path):
            arcpy.AddMessage(
                "ASCII conversion of {0} to raster {1} \n".format(
                    os.path.basename(mess_ascii_path),
                    os.path.basename(out_mess_ras_path)
                )
            )
            # Process ASCII to raster
            arcpy.ASCIIToRaster_conversion(
                mess_ascii_path, out_mess_ras_path, "INTEGER"
            )

    def getRasterFile(self, in_val_raster):
        """ Get row statistics parameters from the value table
            Args:
                in_val_raster: Multi value input raster
            Returns:
                row_count: Input raster counter
                in_ras_file: Input raster file from the multi value parameter
        """
        for i, lst in enumerate(in_val_raster.valueAsText.split(";")):
            row_count = i
            lst_val = super(LandSimilarity, self).formatValueTableData(
                lst)  # Clean mutli value data
            in_ras_file = lst_val[0]
            in_ras_file = in_ras_file.replace("\\", "/")
            yield row_count, in_ras_file  # return values

class LandStatistics(TargetingTool):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Land Statistics"
        self.description = ""
        self.canRunInBackground = False
        self.value_table_cols = 3
        self.scratch_path = arcpy.env.scratchFolder.replace("\\", "/")
        self.parameters = []
        self.spatial_ref = None
        # output = parameter("Output Folder", "out_table", "Workspace",
        #           direction="input")
        # self.parameters.append(output)

    def create_value_table_params(self):
        parms = []

        for i in range(1, 11):
            if i == 1:
                type = 'Required'
            else:
                type = 'Optional'
            parms.append(
                parameter('Raster Layer {}'.format(i), "in_raster{}".format(i),
                          "Raster Layer", parameterType=type)
            )
            parms.append(
                parameter('Statistics Type {}'.format(i),
                          "stat_type{}".format(i),
                          "GPString", parameterType=type)
            )

            parms.append(
                parameter('Field Identifier {}'.format(i),
                          "field_id{}".format(i),
                          "GPString", parameterType=type)
            )

        return parms

    def getParameterInfo(self):
        # TODO move all param definitions to getParameterInfo
        """Define parameter definitions"""
        self.parameters = [
            parameter("Input raster zone data", "in_raszone", "Raster Layer"),
            parameter("Reclassify", "rec_option", "String",
                      parameterType="Optional"),
            parameter("Number of Classes", "num_classes", "Long",
                      parameterType='Optional'),
            parameter("Input remap table", "in_remap_table_view", "Record Set",
                      parameterType='Optional'),
            parameter("From value field", "from_val_field", "Field",
                      parameterType='Optional'),
            parameter("To value field", "to_val_field", "Field",
                      parameterType='Optional'),
            parameter("New value field", "new_val_field", "Field",
                      parameterType='Optional'),
            parameter("Input value feature class", "in_val_fcls",
                      "Feature Layer", parameterType='Optional'),
            parameter("Feature field name", "fval_field", "String",
                      parameterType="Optional")

        ]

        value_table = self.create_value_table_params()
        self.parameters.extend(value_table)

        self.parameters.append(
            parameter("Output Data", "out_data", 'DEDbaseTable',
                      parameterType='Derived', direction='Output'
                      )
        )
        self.parameters.append(
            parameter(
                'E-mails', 'emails', "GPString", parameterType='Optional'
            )
        )
        self.parameters[1].filter.type = "ValueList"
        self.parameters[1].filter.list = ["NONE", "EQUAL INTERVAL",
                                          "RECLASS BY TABLE"]
        self.parameters[1].value = "NONE"  # Default value
        self.parameters[2].enabled = False
        self.parameters[3].enabled = False
        self.parameters[4].parameterDependencies = [self.parameters[3].name]
        self.parameters[4].enabled = False
        self.parameters[5].parameterDependencies = [self.parameters[3].name]
        self.parameters[5].enabled = False
        self.parameters[6].parameterDependencies = [self.parameters[3].name]
        self.parameters[6].enabled = False
        self.parameters[7].filter.list = ["Polygon"]  # Geometry type filter

        for i, param in enumerate(self.parameters):
            if i in [10, 13, 16, 19, 22, 25, 28, 31, 34, 37]:
                if param.value != '' or param.value != "#":
                    self.parameters[i].filter.type = 'ValueList'
                    # TODO remove unused parameters
                    self.parameters[i].filter.list = [
                        "ALL", "MEAN", "MAJORITY", "MAXIMUM", "MEDIAN",
                        "MINIMUM", "MINORITY", "RANGE",
                        "STANDARD DEVIATION",
                        "SUM", "VARIETY"
                    ]

                    # if i in [11, 15, 19, 23, 27, 31, 35, 39, 43, 47]:
                    #     if param.value != '' or param.value != "#":
                    #         self.parameters[i].filter.type = 'ValueList'
                    #
                    #         self.parameters[i].filter.list = ["Yes", "No"]

        # self.parameters[9].columns = [['Raster Layer', 'Raster'],
        #                               ['String', 'Statistics Type'],
        #                               ['String', 'Ignore NoData'],
        #                               ['String', 'Output Table Name'],
        #                               ['String', 'Field Identifier']]
        # self.parameters[9].filters[1].type = 'ValueList'
        #
        # self.parameters[9].filters[1].list = [
        #     "ALL", "MEAN", "MAJORITY", "MAX",
        #     "MAXIMUM", "MEDIAN", "MINIMUM", "MIN", "MINORITY", "RANGE","SD",
        #     "SN", "SR", "STDEV", "STANDARD DEVIATION", "STD", "SUM", "VARIETY"
        # ]
        #
        # self.parameters[9].filters[2].type = 'ValueList'
        #
        # self.parameters[9].filters[2].list = ["Yes", "No"]
        return self.parameters

    def isLicensed(self):
        """ Set whether tool is licensed to execute."""
        spatialAnalystCheckedOut = super(LandStatistics,
                                         self).isLicensed()  # Check availability of Spatial Analyst
        return spatialAnalystCheckedOut

    def updateParameters(self, parameters):
        """ Modify the values and properties of parameters before internal
            validation is performed.  This method is called whenever a parameter
            has been changed.
            Args:
                parameters: Parameters from the tool.
            Returns: Parameter values.
        """
        if parameters[1].value == "EQUAL INTERVAL":
            parameters[2].enabled = True
            if not parameters[2].value:
                parameters[2].value = 5  # Initial value
            self.disableEnableParameter(parameters, 2, 7, False,
                                        enabled_val=True)  # Disable or enable tool parameters
        elif parameters[1].value == "RECLASS BY TABLE":
            if parameters[2].enabled:
                parameters[2].enabled = False
                parameters[2].value = None  # Reset value
            self.disableEnableParameter(parameters, 2, 7, False,
                                        enabled_val=False)
            # Filter table fields data types
            parameters[4].filter.list = ["Short", "Long", "Float", "Single",
                                         "Double"]
            parameters[5].filter.list = ["Short", "Long", "Float", "Single",
                                         "Double"]
            parameters[6].filter.list = ["Short", "Long"]
        else:
            self.disableEnableParameter(parameters, 1, 7, False,
                                        enabled_val=True)
        # Set field values
        if parameters[7].value is not None and parameters[7].altered:

            # TODO add this check on desktop too.
            if arcpy.Exists(parameters[7].value):
                in_fc_field = [f.name for f in
                               arcpy.ListFields(parameters[7].value,
                                                field_type="String")]  # Get string field headers
                parameters[8].filter.list = in_fc_field  # Updated filter list
                if parameters[8].value is None:
                    if len(in_fc_field) > 0:
                        # Set initial field value
                        parameters[8].value = in_fc_field[0]

        else:
            parameters[8].filter.list = []  # Empty filter list
            parameters[8].value = ""  # Reset field value to None

            # # Update value table inputs
            # if parameters[9].value:
            #     if parameters[9].altered:
            #         # in_val_raster = parameters[9]
            #         in_val_raster = self.prepare_value_table(parameters)
            #         # Number of value table columns
            #         vtab = arcpy.ValueTable(self.value_table_cols)
            #         for row_count, ras_val_file, stats_type, data_val, \
            #             out_table_name, table_short_name in \
            #                 self.getStatisticsRasterValue(
            #                 in_val_raster, table_only=False):
            #             if " " in ras_val_file:  # Check if there is space in raster file path
            #                 ras_val_file = "'" + ras_val_file + "'"
            #             if out_table_name is not None:
            #                 if " " in out_table_name:
            #                     out_table_name = "'" + out_table_name + "'"
            #             if stats_type is not None:
            #                 if " " in stats_type:
            #                     stats_type = "'" + stats_type + "'"
            #             # self.updateValueTableInput(parameters, in_val_raster,
            #             #                            ras_val_file, stats_type,
            #             #                            data_val, out_table_name,
            #             #                            table_short_name, vtab)
            # return

    def updateMessages(self, parameters):
        """ Modify the messages created by internal validation for each tool
            parameter.  This method is called after internal validation.
            Args:
                parameters: Parameters from the tool.
            Returns: Internal validation messages.
        """
        in_raster = ""
        in_ras_ref = ""
        if parameters[0].value and parameters[0].altered:
            in_raster = parameters[0].valueAsText.replace("\\", "/")
            in_ras_ref = arcpy.Describe(
                in_raster).SpatialReference  # Get spatial reference of input raster
        if parameters[1].value == "EQUAL INTERVAL" and parameters[2].enabled:
            if parameters[2].value <= 0:
                parameters[2].setErrorMessage(
                    "Class value should be greater than 0")
        if parameters[1].value == "RECLASS BY TABLE" and parameters[3].enabled:
            if parameters[3].value is None:
                parameters[3].setErrorMessage("Input remap table required")
            if parameters[4].value is None:
                parameters[4].setErrorMessage("From value field required")
            if parameters[5].value is None:
                parameters[5].setErrorMessage("To value field required")
            if parameters[6].value is None:
                parameters[6].setErrorMessage("New value field required")
            if parameters[4].value and parameters[5].value:
                warning_message = 'This field is similar to "From value field"'
                self.setFieldWarningMessage(parameters[4], parameters[5],
                                            warning_message)
            if parameters[4].value and parameters[6].value:
                warning_message = 'This field is similar to "From value field"'
                self.setFieldWarningMessage(parameters[4], parameters[6],
                                            warning_message)
            if parameters[5].value and parameters[6].value:
                warning_message = 'This field is similar to "To value field"'
                self.setFieldWarningMessage(parameters[5], parameters[6],
                                            warning_message)
        if parameters[7].value and parameters[7].altered:

            in_fc_para = parameters[7]
            in_fc = parameters[7].valueAsText.replace("\\", "/")
            # Get spatial reference of input value raster
            # in_fc_ref = arcpy.Describe(
            #     in_fc).SpatialReference
            # in_ras_ref_name = in_ras_ref.name
            # in_fc_ref = self.re_project_vector(in_fc, in_ras_ref_name)



            warning_msg = "{0} spatial reference is different from the input {1}"
            super(LandStatistics, self).setSpatialWarning(in_ras_ref,
                                                          in_ras_ref,
                                                          in_fc_para,
                                                          warning_msg,
                                                          in_fc,
                                                          in_raster)  # Set spatial reference warning
        if parameters[9].value and parameters[9].altered:
            in_val_raster = self.prepare_value_table(parameters)
            first_in_raster = in_val_raster[0][0]
            out_table_char = (" ", "_", "-")
            table_short_char = ("_")
            prev_ras_val = []
            prev_table_short_val = []
            prev_table_name_val = []
            for row_count, ras_val_file, stats_type, data_val, out_table_name, \
                table_short_name in self.getStatisticsRasterValue(
                in_val_raster, table_only=False):
                if out_table_name is not None:
                    # Table name validation
                    for str_char in out_table_name:
                        self.charValidator(table_short_name, str_char,
                                           out_table_char,
                                           field_id=False)  # Validated field value
                # Input raster value validation
                if len(prev_ras_val) > 0:
                    super(LandStatistics, self).uniqueValueValidator(
                        prev_ras_val, ras_val_file, first_in_raster,
                        field_id=False)  # Set duplicate input warning
                    prev_ras_val.append(ras_val_file)
                else:
                    prev_ras_val.append(ras_val_file)
                # Set spatial reference warning
                if parameters[0].value and parameters[0].altered:
                    # Get spatial reference of input value raster
                    ras_val_ref = arcpy.Describe(ras_val_file).SpatialReference
                    warning_msg = "{0} spatial reference is different from the input {1}"
                    # Set spatial reference warning
                    super(LandStatistics, self).setSpatialWarning(
                        in_ras_ref, ras_val_ref, first_in_raster, warning_msg,
                        ras_val_file, in_raster)
                # Set error message for statistics type
                # self.statisticsTypeErrorMessage(in_val_raster, stats_type)
                # Ignore NoData validation
                if data_val is not None:
                    if data_val.lower() != "yes":
                        if data_val.lower() != "no":
                            data_val.setErrorMessage(
                                "Ignore NoData field expects "
                                "\"Yes\" or \"No\" input value")
                # # Field identifier validation
                # if len(in_val_raster) > 1:
                # Validated field identifier input
                # Value table field identifier validator
                self.fielIdValidator(table_short_name, first_in_raster,
                                     table_short_char)
                if len(prev_table_short_val) > 0:
                    super(LandStatistics, self).uniqueValueValidator(
                        prev_table_short_val, table_short_name.valueAsText,
                        first_in_raster, field_id=True)
                    prev_table_short_val.append(table_short_name.valueAsText)
                else:
                    prev_table_short_val.append(table_short_name.valueAsText)
                # Validated output table name input
                if len(prev_table_name_val) > 0:
                    super(LandStatistics, self).uniqueValueValidator(
                        prev_table_name_val, out_table_name, first_in_raster,
                        field_id=True)
                    prev_table_name_val.append(out_table_name)
                else:
                    prev_table_name_val.append(out_table_name)

    def re_project_vector(self, in_fc, srid_desc):
        dsc = arcpy.Describe(in_fc)
        srs = None
        if dsc.spatialReference.Name == "Unknown":
            arcpy.AddMessage(
                'skipped this layer due to undefined coordinate system: '
                + in_fc
            )
        else:
            # Set output coordinate system
            outCS = arcpy.SpatialReference(srid_desc)
            # run project tool
            arcpy.Project_management(in_fc, in_fc, outCS)
            srs = arcpy.Describe(in_fc).SpatialReference
        return srs

    def execute(self, parameters, messages):
        """ Execute functions to process input raster.
            Args:
                parameters: Parameters from the tool.
                messages: Internal validation messages
            Returns: Land statistics table.
        """
        try:
            in_raster = parameters[0].valueAsText.replace("\\", "/")
            # Get output folder path
            # out_table = parameters[39].valueAsText.replace("\\", "/")
            self.spatial_ref = self.get_srid_from_file(in_raster)
            ras_temp_path = self.scratch_path + '/'  # '/Temp/'

            if not os.path.exists(ras_temp_path):
                os.makedirs(ras_temp_path)  # Create temporary directory

            # Feature class rasterization and overlay
            # TODO apply this condition on the desktop version
            if parameters[7].value is not None:
                # TODO add this check on desktop too.
                if arcpy.Exists(parameters[7].value):
                    in_fc = \
                        super(LandStatistics, self).getInputFc(parameters[7])[
                            "in_fc"]  # Get feature file path
                    in_fc_file = \
                        super(LandStatistics, self).getInputFc(parameters[7])[
                            "in_fc_file"]  # Get feature file name

                    fc_describe = arcpy.Describe(in_fc)
                    fc_sr = fc_describe.spatialReference
                    # TODO check if feature layer works in the desktop version

                    if fc_sr.Name != self.spatial_ref.Name:

                        arcpy.AddMessage(
                            "Re-projecting polygon {0} \n".format(
                                os.path.basename(in_fc_file))
                        )
                        fc_dir = os.path.dirname(in_fc)
                        fc_name = os.path.basename(in_fc)

                        if len(fc_name.split('.', 1)) > 1:
                            proj_name = fc_name.split('.', 1)[0],
                            proj_ext = fc_name.split('.', 1)[1]
                            proj_fc_name = '{}_1.{}'.format(proj_name,
                                                            proj_ext)
                            proj_fc = '{}/{}'.format(fc_dir, proj_fc_name)

                            arcpy.Copy_management(in_fc,
                                                  ras_temp_path + fc_name)
                            arcpy.Project_management(
                                ras_temp_path + fc_name,
                                ras_temp_path + proj_fc_name, self.spatial_ref
                            )
                            in_fc = ras_temp_path + proj_fc_name
                        else:

                            proj_fc_name = '{}_1'.format(fc_name)
                            desc = arcpy.Describe(fc_name)
                            path = desc.path
                            path_dir = os.path.dirname(path)
                            old_fc = '{}/{}'.format(path_dir, fc_name)
                            new_fc = '{}/{}'.format(path_dir, proj_fc_name)
                            arcpy.Project_management(
                                old_fc, new_fc, self.spatial_ref
                            )
                            in_fc = new_fc

                    in_fc_field = parameters[8].valueAsText

                    try:
                        arcpy.AddMessage(
                            "Converting polygon {0} to raster \n".format(
                                os.path.basename(in_fc_file))
                        )
                        # Convert polygon to raster
                        arcpy.PolygonToRaster_conversion(
                            in_fc, in_fc_field, ras_temp_path + "ras_poly",
                            "CELL_CENTER", "NONE", in_raster
                        )

                        arcpy.gp.Times_sa(ras_temp_path + "ras_poly", "1000",
                                          ras_temp_path + "ras_multi")  # Process: Times
                        # Reclassify input raster
                        in_raster = self.reclassifyRaster(parameters,
                                                          ras_temp_path)
                        self.zonalStatisticsInit(in_raster, ras_temp_path,
                                                 parameters,
                                                 ras_add=True)
                        self.configZonalStatisticsTable(parameters, ras_temp_path,
                                                        self.scratch_path,
                                                        in_vector=True)
                    except Exception as ex:
                        arcpy.AddMessage('{0}. \n'
                                         'Proceeding without Feature Class.\n'.format(ex))
                        in_raster = self.reclassifyRaster(parameters,
                                                          ras_temp_path)
                        self.zonalStatisticsInit(in_raster, ras_temp_path,
                                                 parameters,
                                                 ras_add=False)
                        self.configZonalStatisticsTable(parameters,
                                                        ras_temp_path,
                                                        self.scratch_path,
                                                        in_vector=False)

            else:
                in_raster = self.reclassifyRaster(parameters, ras_temp_path)
                self.zonalStatisticsInit(in_raster, ras_temp_path, parameters,
                                         ras_add=False)
                self.configZonalStatisticsTable(parameters, ras_temp_path,
                                                self.scratch_path,
                                                in_vector=False)

                # shutil.rmtree(ras_temp_path)  # delete folder
                # arcpy.RefreshCatalog(self.scratch_path)  # Refresh folder

        except Exception as ex:
            tb = sys.exc_info()[2]
            # tbinfo = traceback.format_tb(tb)[0]
            # pymsg = "PYTHON ERRORS:\nTraceback info:\n" + tbinfo + "\nError Info:\n" + str(sys.exc_info()[1])
            msgs = "ArcPy ERRORS:\n" + arcpy.GetMessages(2) + "\n"
            arcpy.AddError(''.join(traceback.format_tb(tb)))
            # arcpy.AddError(pymsg)
            arcpy.AddError(msgs)
            arcpy.AddMessage('ERROR: {0} \n'.format(ex))

    def disableEnableParameter(self, parameters, val_1, val_2, boolean_val,
                               enabled_val):
        """Disable or enable tool parameters
            Args:
                parameters: Tool parameters
                val_1: First comparison value
                val_2: Second comparison value
                boolean_val: Boolean value
            Return: None
        """
        for i, item in enumerate(parameters):
            if (i > val_1) and (i < val_2):
                if enabled_val:
                    if parameters[i].enabled:
                        if not boolean_val:
                            parameters[i].value = None  # Reset values
                        parameters[i].enabled = boolean_val
                else:
                    parameters[i].enabled = True

    def updateValueTableInput(self, parameters, in_val_raster, ras_val_file,
                              stats_type, data_val, out_table_name,
                              table_short_name, vtab):
        """ Update value parameters in the tool.
            Args:
                parameters: Tool parameters
                in_val_raster: Input value raster parameter
                ras_val_file: Input value raster
                stats_type: Statistic type to be calculated
                data_val: Denotes whether NoData values in the Value input will influence the results or not
                out_stat_table: Output zonal statistics table
                table_short_name: Unique string to be concatenated with table field name
                vtab: Number of value table columns
            Returns: Parameter values.
        """
        if table_short_name == "#":
            vtab.addRow('{0} {1} {2} {3} {4}'.format(ras_val_file, stats_type,
                                                     data_val, out_table_name,
                                                     "#"))
            in_val_raster.value = vtab.exportToString()
        if table_short_name != "#":
            vtab.addRow('{0} {1} {2} {3} {4}'.format(ras_val_file, stats_type,
                                                     data_val, out_table_name,
                                                     table_short_name))
            in_val_raster.value = vtab.exportToString()

    def setFieldWarningMessage(self, parameter_1, parameter_2,
                               warning_message):
        """ Set warning messages on input table fields
            Args:
                parameter_1: Input table field parameter
                parameter_2: Input table field parameter
                warning_message: Field warning message
            Return: None
        """
        if parameter_1.altered or parameter_2.altered:
            if parameter_1.valueAsText == parameter_2.valueAsText:
                parameter_2.setWarningMessage(warning_message)

    def statisticsTypeErrorMessage(self, in_val_raster, stats_type):
        """ Set error message for statistics type
            Args:
                in_val_raster: Input value raster
                stats_type: Input statistics type from the value table
            Return: None
        """
        if stats_type.valueAsText.upper() not in ["ALL", "MEAN", "MAJORITY",
                                                  "MAX",
                                                  "MAXIMUM", "MEDIAN",
                                                  "MINIMUM", "MIN",
                                                  "MINORITY", "RANGE",
                                                  "SD", "SN", "SR", "STDEV",
                                                  "STANDARD DEVIATION", "STD",
                                                  "SUM",
                                                  "VARIETY"]:
            stats_type.setErrorMessage(
                "Allowed Statistics type: {0}".format(
                    "ALL | MEAN | MAJORITY | MAX | MAXIMUM | MEDIAN | MINIMUM | MIN | MINORITY | "
                    "RANGE | SUM | VARIETY | STD | SD | SN | SR | STDEV | STANDARD DEVIATION"
                ))

    def fielIdValidator(self, table_short_name, in_val_raster,
                        table_short_char):
        """ Value table field identifier validator
            Args:
                table_short_name: Value table field identifier column value
                in_val_raster: Input value raster
                table_short_char: esc_char: Escape characters
            Returns: None
        """
        if table_short_name.valueAsText is None:
            return

        if len(table_short_name.valueAsText) > 2:
            table_short_name.setErrorMessage(
                "Field identifier field cannot have more than two values"
            )
        elif table_short_name.valueAsText[0].isdigit():
            table_short_name.setErrorMessage(
                "Field identifier value cannot start with a digit"
            )
        elif table_short_name.valueAsText.startswith("_"):
            table_short_name.setErrorMessage(
                "Field identifier value cannot start with an  underscore"
            )
        for str_char in table_short_name.valueAsText:
            # Validated field value
            self.charValidator(table_short_name.valueAsText, str_char,
                               table_short_char, field_id=True)

    def charValidator(self, in_val_raster, str_char, esc_char, field_id):
        """ Validated string character
            Args:
                in_val_raster: Input value raster
                str_char: String character
                esc_char: Escape characters
                field_id: Check if field identifier column is to be validated or not
            Returns: None
        """
        # Check for invalid values
        if str_char.isalnum() is False and str_char not in esc_char:
            if field_id:
                if str_char == " ":
                    in_val_raster.setErrorMessage(
                        "Space is not allowed. Use an underscore instead".format(
                            str_char))
            if str_char == "#":
                in_val_raster.setErrorMessage("Column value is missing")
            else:
                in_val_raster.setErrorMessage(
                    "{0} is not a valid character for this field".format(
                        str_char))

    def reclassifyRaster(self, parameters, ras_temp_path):
        """ Reclassify input raster
            Args:
                parameters: Parameters from the tool.
                ras_temp_path: Temporary folder
            Return:
                reclass_raster: Reclassified input raster
        """
        reclass_raster = ""
        in_raster = parameters[0].valueAsText.replace("\\", "/")
        if parameters[1].value == "EQUAL INTERVAL":
            stat_raster = super(LandStatistics, self).calculateStatistics(
                in_raster)

            # TODO change on the dekstop version remove arcpy.Raster with the file
            min_val = stat_raster.minimum  # Minimum input raster value
            max_val = stat_raster.maximum  # Maximum input raster value
            num_cls = parameters[2].value
            cls_width = float(max_val - min_val) / num_cls  # Class width
            if cls_width.is_integer():
                cls_width = int(cls_width)  # Convert to integer
            arcpy.AddMessage(
                "Creating reclassify range for {0} \n".format(
                    os.path.basename(in_raster)))
            equal_interval_val = self.getEqualIntervalRemapVal(min_val,
                                                               cls_width,
                                                               num_cls)  # List of reclassify value lists
            self.createEqualIntervalValLog(parameters,
                                           equal_interval_val)  # Create a log of equal interval values
            arcpy.AddMessage(
                "Reclassifying {0} \n".format(os.path.basename(in_raster)))
            reclass_raster = self.reclassifyEqualInterval(in_raster,
                                                          ras_temp_path,
                                                          equal_interval_val)  # Reclassify input raster layer
        elif parameters[1].value == "RECLASS BY TABLE":
            in_table = parameters[3].valueAsText
            from_val = parameters[4].valueAsText
            to_val = parameters[5].valueAsText
            new_val = parameters[6].valueAsText
            arcpy.AddMessage(
                "Reclassifying {0} \n".format(os.path.basename(in_raster)))

            arcpy.gp.ReclassByTable_sa(in_raster, in_table, from_val, to_val,
                                       new_val, ras_temp_path + "ras_reclass",
                                       "DATA")  # Process: Reclass by Table
            reclass_raster = ras_temp_path + "ras_reclass"
        else:
            # TODO check why NONE results in no combined dbf file.
            reclass_raster = in_raster
        return reclass_raster

    def getEqualIntervalRemapVal(self, min_val, cls_width, num_cls):
        """ Create list of equal interval reclassify value lists
            Args:
                parameters: Parameters from the tool.
                min_val: Minimum input raster value
                cls_width: Class width
                num_cls: Number of classes
            Return:
                equal_interval_val: A list of list with reclassify values
        """
        equal_interval_val = []
        prev_count = 0
        for i in xrange(1, num_cls + 1):
            remap_range_val = []
            for j in xrange(1):
                if i == 1:
                    remap_range_val.append(min_val)
                    remap_range_val.append(min_val + cls_width)
                    remap_range_val.append(i)
                elif i == 2:
                    remap_range_val.append(min_val + cls_width)
                    remap_range_val.append(min_val + (cls_width * i))
                    remap_range_val.append(i)
                else:
                    remap_range_val.append(min_val + (cls_width * prev_count))
                    remap_range_val.append(min_val + (cls_width * i))
                    remap_range_val.append(i)
            equal_interval_val.append(remap_range_val)
            prev_count = i
        return equal_interval_val

    def createEqualIntervalValLog(self, parameters, interval_val):
        """ Create a log of equal interval values used in reclassification of raster
            Args:
                parameters: Parameters from the tool.
                interval_val: A list of list with reclassify values.
            Return: None
        """
        # # Get output folder path
        # out_dir = parameters[39].valueAsText.replace("\\", "/")
        interval_log_txt = self.scratch_path + "/equal_interval_log.txt"
        t = time.localtime()
        local_time = time.asctime(t)
        with open(interval_log_txt, "w") as f:
            f.write(" " + local_time + " \n")
            f.write("\n")
            f.write(" Equal Interval Values \n")
            f.write(" ====================== \n")
            f.write("\n")
            f.write(" Number of Classes: " + str(len(interval_val)) + "\n")
            f.write("\n")
            f.write(
                "  From Value            To Value            Output Value \n")
            f.write(
                " ------------          ----------          -------------- \n")
            f.write("\n")
            for item in interval_val:
                val = "  " + str(item[0]) + "                   " + str(
                    item[1]) + "                 " + str(item[2])
                f.write(val + "\n")

    def reclassifyEqualInterval(self, in_raster, ras_temp_path, remap_val):
        """ Reclassify input raster layer
            Args:
                in_raster: Input land suitability raster
                ras_temp_path: Temporary folder
                remap_val: Input raster reclassify values
            Return: Reclassified raster temporary path
        """
        remap_val_range = arcpy.sa.RemapRange(remap_val)
        reclass_raster = arcpy.sa.Reclassify(in_raster, "Value",
                                             remap_val_range,
                                             "DATA")  # Process: Reclassify
        reclass_raster.save(ras_temp_path + "ras_reclass")
        return ras_temp_path + "ras_reclass"

    def zonalStatisticsInit(self, in_raster, ras_temp_path, parameters,
                            ras_add):
        """ Initialize the zonal statistics calculation process
            Args:
                in_raster: Input land suitability raster.
                ras_temp_path: Temporary folder
                parameters: Tool parameters
                ras_add: Variable to hint if another process should take place or not
            Returns: None.
        """
        # in_val_raster = parameters[9]
        in_val_raster = self.prepare_value_table(parameters)
        if ras_add:
            arcpy.AddMessage("Initializing land statistics \n")
            arcpy.AddMessage(
                "Adding {0} to {1} \n".format(
                    os.path.basename(ras_temp_path) + "ras_multi",
                    os.path.basename(in_raster)))
            arcpy.gp.Plus_sa(ras_temp_path + "ras_multi", in_raster,
                             ras_temp_path + "ras_plus")  # Process: Plus
            super(LandStatistics, self).deleteFile(ras_temp_path, "ras_multi",
                                                   "ras_reclass")  # Delete file
            in_raster = ras_temp_path + "ras_plus"
            ras_copy = self.convertRasterPixelType(in_raster,
                                                   ras_temp_path)  # Convert float/double precision to 32 bit integer
            if ras_copy is not None:
                in_raster = ras_copy
            arcpy.AddMessage(
                "Building raster attribute table for {0} \n".format(
                    os.path.basename(in_raster)))
            arcpy.BuildRasterAttributeTable_management(in_raster,
                                                       "Overwrite")  # Build attribute table for raster
            for row_count, ras_val_file, stats_type, data_val, out_table_name, table_short_name in self.getStatisticsRasterValue(
                    in_val_raster, table_only=False):
                stats_type_edit = self.formatStatisticsType(stats_type.value)

                out_stat_table = ras_temp_path + out_table_name + ".dbf"
                self.calculateZonalStatistics(in_raster, ras_val_file,
                                              stats_type_edit, data_val,
                                              out_stat_table)
            super(LandStatistics, self).deleteFile(
                ras_temp_path, "ras_plus", "ras_copy"
            )

        else:
            ras_copy = self.convertRasterPixelType(in_raster, ras_temp_path)
            if ras_copy is not None:
                in_raster = ras_copy
            arcpy.AddMessage(
                "Building raster attribute table for {0} \n".format(
                    os.path.basename(in_raster)))
            # Build attribute table for raster
            arcpy.BuildRasterAttributeTable_management(in_raster, "Overwrite")
            for row_count, ras_val_file, stats_type, data_val, out_table_name, \
                table_short_name in self.getStatisticsRasterValue(
                in_val_raster, table_only=False):
                stats_type_edit = self.formatStatisticsType(stats_type.value)

                out_stat_table = ras_temp_path + out_table_name + ".dbf"
                self.calculateZonalStatistics(in_raster, ras_val_file,
                                              stats_type_edit, data_val,
                                              out_stat_table)
            super(LandStatistics, self).deleteFile(ras_temp_path,
                                                   "ras_reclass", "ras_copy")

    def get_value_table_count(self, parameters):

        count = 0
        for i in [9, 12, 15, 18, 21, 24, 27, 30, 33, 36]:

            if isinstance(parameters[i].valueAsText, unicode):
                count = count + 1
        return count

    def prepare_value_table(self, parameters):
        row_count = self.get_value_table_count(parameters)

        column_count = self.value_table_cols
        value_table = []
        for row in range(0, row_count):

            column = []
            for col in range(row * column_count + 9,
                             column_count + row * column_count + 9):
                param = parameters[col]

                column.append(param)
            value_table.append(column)
        return value_table

    def getStatisticsRasterValue(self, in_val_raster, table_only):
        """ Get row statistics parameters from the value table
            Args:
                in_val_raster: Value table parameter with the statistics parameters
            Return:
        """
        for i, lst in enumerate(in_val_raster):  # .valueAsText.split(";")):
            row_count = i
            # Clean value table data
            # lst_val = super(LandStatistics, self).formatValueTableData(lst)

            lst_val = lst
            ras_val_file = lst_val[0].valueAsText

            ras_val_file = ras_val_file.replace("\\", "/")
            stats_type = lst_val[1]

            out_table_name = ntpath.basename(ras_val_file).replace('.', '')

            table_short_name = lst_val[2]
            data_val = 'Yes'

            # Check if data is empty
            if not table_only:
                if stats_type == "#":
                    stats_type = "ALL"
                    # Get input raster file name
                    # out_table_name = ntpath.basename(ras_val_file)
                    # Get input raster file name without extension
                    out_table_name = os.path.splitext(out_table_name)[
                        0].rstrip()
                    yield row_count, ras_val_file, stats_type, \
                          data_val, out_table_name, table_short_name
                else:
                    yield row_count, ras_val_file, stats_type, \
                          data_val, out_table_name, table_short_name
            else:
                yield row_count, out_table_name, table_short_name.valueAsText

    def convertRasterPixelType(self, in_raster, ras_temp_path):
        """ Convert float/double precision raster to 32 bit signed integer pixel type
            Args:
                in_raster: Input land suitability raster.
                ras_temp_path: Temporary folder
            Returns: A 32 bit signed integer raster.
        """
        ras_desc = arcpy.Describe(in_raster)
        # Check raster pixel type and copy raster
        if ras_desc.pixelType in ["F32", "F64"]:
            in_raster_obj = super(LandStatistics, self).calculateStatistics(
                in_raster)
            minVal = in_raster_obj.minimum  # Minimum raster value
            minVal -= 1
            # Convert float/double precision raster to 32 bit signed integer
            arcpy.AddMessage(
                "Converting {0} to a 32 bit signed {1} \n".format(
                    os.path.basename(in_raster),
                    os.path.basename(ras_temp_path) + "ras_copy")
            )
            arcpy.CopyRaster_management(in_raster, ras_temp_path + "ras_copy",
                                        "", "", str(minVal), "NONE", "NONE",
                                        "32_BIT_SIGNED", "NONE", "NONE")
            return ras_temp_path + "ras_copy"

    def formatStatisticsType(self, stats_type):
        """ Format statistics type string to the right format
            Args:
                stats_type: Value table statistics type input
        """
        # stats_type = stats_type.valueAsText.upper()
        if stats_type == "MAX":
            stats_type_edit = "MAXIMUM"
        elif stats_type == "MIN":
            stats_type_edit = "MINIMUM"
        elif stats_type in ["SD", "SN", "SR", "STDEV", "STANDARD DEVIATION"]:
            stats_type_edit = "STD"
        else:
            stats_type_edit = stats_type
        return stats_type_edit

    def calculateZonalStatistics(self, in_raster, ras_val_file,
                                 stats_type_edit, data_val, out_stat_table):
        """ Calculate statistics on a given area  of interest - zone
            Args:
                in_raster: Input land suitability raster or plus raster
                in_val_raster: Raster that contains the values on which to calculate a statistic.
                data_val: Denotes whether NoData values in the Value input will influence the results or not
                stats_type: Statistic type to be calculated
                out_stat_table: Output zonal statistics table
            Returns: Saves a dbf table to memory
        """

        if data_val is not None:
            if data_val.lower() == "yes":
                arcpy.AddMessage(
                    "Calculating land statistics for {0}\n".format(
                        os.path.basename(ras_val_file)))
                arcpy.gp.ZonalStatisticsAsTable_sa(in_raster, "Value",
                                                   ras_val_file,
                                                   out_stat_table,
                                                   "DATA",
                                                   stats_type_edit)  # Process: Zonal Statistics as Table
            else:
                arcpy.AddMessage(
                    "Calculating land statistics for {0} \n".format(
                        os.path.basename(ras_val_file)))
                arcpy.gp.ZonalStatisticsAsTable_sa(in_raster, "Value",
                                                   ras_val_file,
                                                   out_stat_table,
                                                   "NODATA",
                                                   stats_type_edit)  # Process: Zonal Statistics as Table

    def configZonalStatisticsTable(self, parameters, ras_temp_path, out_table,
                                   in_vector):
        """ Manipulate zonal statistics table
            Args:
                parameters: Value table input parameters
                ras_temp_path: Temporary folder
                out_table: Output zonal statistics directory
                in_vector: Input feature class
            Return: None
        """
        # in_val_raster = parameters[9]
        in_val_raster = self.prepare_value_table(parameters)
        first_stat_table = ""
        single_out_stat_table = ""
        single_move_stat_table = ""

        # TODO change double loop on desktop version and replace the whole method

        # if len(in_val_raster) > 1:
        for row_count, out_table_name, table_short_name in self.getStatisticsRasterValue(
                in_val_raster, table_only=True):
            if row_count == 0:
                first_stat_table = ras_temp_path + out_table_name + "_view" + ".dbf"
                single_out_stat_table = ras_temp_path + out_table_name + ".dbf"
                # single_move_stat_table = out_table + "/" + out_table_name + ".dbf"
            # if len(in_val_raster) > 1:
            #     if row_count == 0:
            #         first_stat_table = ras_temp_path + out_table_name + "_view" + ".dbf"
            table_short_name = table_short_name.upper()
            if len(in_val_raster) > 1:
                try:
                    self.updateZonalStatisticsTable(out_table, ras_temp_path,
                                                    row_count, out_table_name,
                                                    first_stat_table,
                                                    table_short_name)
                except Exception as ex:
                    arcpy.AddMessage(ex)
        if len(in_val_raster) > 1:
            self.addFieldValueZonalStatisticsTable(
                parameters, out_table, ras_temp_path, first_stat_table,
                in_val_raster
            )
        else:
            # if in_vector:
            # Even if there is nothing to combine, output should be the same
            self.addFieldValueZonalStatisticsTable(
                parameters, out_table, ras_temp_path, single_out_stat_table,
                in_val_raster
            )

            # else:
            #


            # if in_vector:
            #     self.addFieldValueZonalStatisticsTable(
            #         parameters, out_table, ras_temp_path, single_out_stat_table,
            #         in_val_raster
            #     )
            # else:
            # Add new fields and values

            # arcpy.AddMessage(
            #     "Moving file {0} to {1} \n".format(single_out_stat_table,
            #                                        single_move_stat_table))
            # self.moveFile(single_out_stat_table, single_move_stat_table)

    def updateZonalStatisticsTable(self, out_table, ras_temp_path, row_count,
                                   out_table_name, first_stat_table,
                                   table_short_name):
        """ Edit zonal statistics output table
            Args:
                out_table: Ouput folder
                ras_temp_path: Temporary folder
                row_count: Number of rows with input in the value table
                out_table_name: Output .dbf table name
                first_stat_table: First output table name in the value table input
                table_short_name: A short name to append to table columns
            Return: None
        """
        out_stat_table = ras_temp_path + out_table_name + ".dbf"
        move_stat_table = out_table + "/" + out_table_name + ".dbf"
        arcpy.AddMessage(
            "Renaming fields in {0} \n".format(out_table_name + ".dbf"))
        out_table_view = self.renameTableField(out_stat_table, out_table_name,
                                               table_short_name,
                                               ras_temp_path)  # Rename table fields
        arcpy.AddMessage("Moving file {0} to {1} \n".format(
            os.path.basename(out_stat_table),
            os.path.basename(move_stat_table)))
        # Move original tables to output folders
        self.moveFile(out_stat_table, move_stat_table)
        if row_count > 0:
            # Get all field names
            field_names = [f.name for f in arcpy.ListFields(out_table_view)]
            # Fields to be excluded in the join
            del_fields = ["OID", "VALUE", "COUNT"]
            # Fields to included in the join
            req_fields = [i for i in field_names if i not in del_fields]

            arcpy.AddMessage("Joining {0} to {1} \n".format(
                os.path.basename(out_table_view),
                os.path.basename(first_stat_table))
            )
            arcpy.JoinField_management(first_stat_table, "VALUE",
                                       out_table_view, "VALUE",
                                       req_fields)  # Join tables
            arcpy.management.Delete(out_table_view)

    def renameTableField(self, out_stat_table, out_table_name,
                         table_short_name, ras_temp_path):
        """ Rename table fields
            Args:
                out_stat_table: Output table path
                out_table_name: Output table name
                table_short_name: Field keyword
                ras_temp_path: Temporary folder
            return:
                out_table_view: a table with renamed fields
        """
        fields = arcpy.ListFields(out_stat_table)  # Get fields
        fieldinfo = arcpy.FieldInfo()  # Create a fieldinfo object
        # Iterate through the fields and set them to fieldinfo
        for field in fields:
            if field.name in ["AREA", "MIN", "MAX", "RANGE", "MEAN", "STD",
                              "SUM", "VARIETY", "MAJORITY", "MINORITY",
                              "MEDIAN"]:
                fieldinfo.addField(field.name,
                                   table_short_name + "_" + field.name,
                                   "VISIBLE", "")
        view_table = out_table_name + "_view"
        # Create a view layer in memory with fields as set in fieldinfo object
        arcpy.MakeTableView_management(out_stat_table, view_table, "", "",
                                       fieldinfo)
        # make a copy of the view in disk
        arcpy.CopyRows_management(view_table,
                                  ras_temp_path + view_table + ".dbf")
        out_table_view = ras_temp_path + view_table + ".dbf"
        if arcpy.Exists(view_table):
            arcpy.Delete_management(view_table)  # delete view if it exists
        return out_table_view

    def moveFile(self, current_path, new_path):
        """ Move a table from the current directory to another
            Args:
                current_path: Current location of the file
                new_path: The new directory to move the file to
            Return: None
        """
        # Move individual tables to output folder
        if os.path.isfile(current_path):
            shutil.move(current_path, new_path)

    def addFieldValueZonalStatisticsTable(
            self, parameters, out_table, ras_temp_path, first_stat_table,
            value_table):
        """ Add new fields and values to the zonal statistics table
            Args:
                parameters: Tool parameters
                out_table: Ouput folder
                ras_temp_path: Temporary folder
                first_stat_table: First output table name in the value table input
        """

        # Add new fields and data
        # if len(value_table) > 1:
        combined_stat_table = out_table + "/All_Zonal_Stat.dbf"
        # else:
        #     in_dbf_file = ntpath.basename(first_stat_table)
        #     combined_stat_table = out_table + "/" + in_dbf_file

        if parameters[7].value is not None and arcpy.Exists(first_stat_table):
            try:
                in_fc_field = parameters[8].valueAsText
                ras_poly = ras_temp_path + "ras_poly"
                try:
                    if not arcpy.ListFields(first_stat_table, in_fc_field):
                        arcpy.AddMessage(
                            "Adding fields to {0} \n".format(
                                os.path.basename(first_stat_table)))
                        # Adds field to a .dbf table
                        self.addTableField(first_stat_table, in_fc_field)
                except Exception as ex:
                    arcpy.AddMessage(ex)
                # Process: Calculate Field

                # TODO please check with Nicholas the use of this.
                # # arcpy.CalculateField_management(first_stat_table, "POLY_VAL",
                # #                                 "(!VALUE! - str((!VALUE![3:])) / 1000",
                # #                                 "PYTHON", "")
                #
                try:
                    arcpy.AddMessage(
                        "Adding suitability rank values to new fields in {0} \n".format(
                            os.path.basename(first_stat_table)))
                    arcpy.CalculateField_management(first_stat_table, "LAND_RANK",
                                                    "str(!VALUE!)[3:]", "PYTHON", "")
                except Exception as ex:
                    arcpy.AddMessage(
                        "{} \n".format(ex)
                    )
                # arcpy.CalculateField_management(first_stat_table, "POLY_VAL",
                #                                 "([VALUE] - Right([VALUE] , 3)) / 1000",
                #                                 "VB", "")
                # arcpy.CalculateField_management(first_stat_table, "LAND_RANK",
                #                                 "Right([VALUE] , 3)", "VB", "")
                # Add values to table
                arcpy.AddMessage("Adding ID values to new fields in {0} \n".format(
                    os.path.basename(first_stat_table)))
                try:
                    self.addValuesZonalStatisticsTable(in_fc_field, ras_poly,
                                                       first_stat_table)
                except Exception as ex:
                    arcpy.AddMessage(
                        "Error: {} \n".format(ex)
                    )

                arcpy.AddMessage(
                    "Moving file {0} to {1} \n".format(
                        os.path.basename(first_stat_table),
                        os.path.basename(combined_stat_table))
                )
                self.moveFile(first_stat_table, combined_stat_table)
            except Exception as ex:
                arcpy.AddMessage(
                    "Error: {} \n".format(ex)
                )
                arcpy.AddMessage(
                    "Moving file {0} to {1} \n".format(
                        os.path.basename(first_stat_table),
                        os.path.basename(combined_stat_table))
                )

                self.moveFile(first_stat_table, combined_stat_table)
        else:
            arcpy.AddMessage(
                "Moving file {0} to {1} \n".format(
                    os.path.basename(first_stat_table),
                    os.path.basename(combined_stat_table))
            )

            self.moveFile(first_stat_table, combined_stat_table)

        arcpy.SetParameterAsText(39, combined_stat_table)

        self.submit_message(combined_stat_table, parameters[40], self.label)

    def addTableField(self, first_stat_table, in_fc_field):
        """ Adds field to a .dbf table
            Args:
                in_fc_field: Feature name field
                first_stat_table: First output table name in the value table input
            Return: None
        """
        arcpy.AddField_management(first_stat_table, in_fc_field, "STRING")
        arcpy.AddField_management(first_stat_table, "POLY_VAL", "LONG")
        arcpy.AddField_management(first_stat_table, "LAND_RANK", "LONG")

    def addValuesZonalStatisticsTable(self, in_fc_field, ras_poly,
                                      out_stat_table):
        """ Copy field values from one table to another
            Args:
                in_fc_field: Input feature class field name
                ras_poly: Rasterized polygon
                out_stat_table: Output zonal statistics table
        """
        with arcpy.da.SearchCursor(ras_poly, ["VALUE"]) as cursor:
            for row in cursor:
                sql_exp1 = "VALUE = " + str(row[0])  # SQL expression
                sql_exp2 = "POLY_VAL = " + str(row[0])
                with arcpy.da.SearchCursor(ras_poly, [in_fc_field],
                                           sql_exp1) as cursor2:
                    for row2 in cursor2:
                        update_val = row2[0]
                        with arcpy.da.UpdateCursor(out_stat_table,
                                                   [in_fc_field],
                                                   sql_exp2) as cursor3:  # Update values in the second table
                            for row3 in cursor3:
                                row3[0] = update_val
                                cursor3.updateRow(row3)
        # Process: Delete Field
        arcpy.DeleteField_management(out_stat_table, "POLY_VAL")
        arcpy.management.Delete(ras_poly)  # Delete polygon
