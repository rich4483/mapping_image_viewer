import os

# NOTE: This must be performed before boto3 is loaded, directly or indirectly via other imports.
import ushr.qc.app.env
ushr.qc.app.env.set_aws_env()

import time
import sys
import requests
import json
from datetime import datetime as dt
import geoalchemy2
import shapely
import logging
from display import Ui_Form
from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtWidgets import QMainWindow, QSizePolicy
from PyQt5.QtCore import pyqtSignal, pyqtSlot, Qt
from PyQt5.QtCore import QDate
from PyQt5.QtCore import QTime
from PyQt5.QtCore import QThread
import ushr.acorn.datalake.utils
from ushr.acorn.cloud.boto_helpers import upload_file
from ushr.acorn.cloud.boto_helpers import download_file
from common import __version__, USHR_ICON
from PIL import Image
import creds

log = logging.getLogger(__name__)

FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'main.ui'))

METERS_PER_DEGREE = 111139

class MainWindow(QMainWindow, FORM_CLASS):

    def __init__(self):
        super().__init__()
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object
        # by doing self.<objectname>,
        # and you can use autoconnect slots.
        self.setupUi(self)

        self.setWindowTitle("Nexar Image Tool - version " + __version__)
        self.setWindowIcon(QtGui.QIcon(USHR_ICON))

        # Initialize interface to one line coordinates.
        self.single_coords = True
        self.line_edit_latitude.show()
        self.label_latitude.hide()
        self.label_longitude.hide()
        self.line_edit_longitude.hide()
        # Set default longitude, latitude
        self.line_edit_latitude.setText('-84.21422089, 33.98343972')
        self.combo_coords.currentIndexChanged.connect(self.on_combo_coords_selection_changed)

        self.direction_buttons = [self.button_north, self.button_south, self.button_east, self.button_west,
                                  self.button_northwest, self.button_northeast, self.button_southwest,
                                  self.button_southeast]

        self.image_buttons = [self.button_image1, self.button_image2, self.button_image3, self.button_image4,
                              self.button_image5, self.button_image6, self.button_image7, self.button_image8]

        self.interface_buttons = [self.button_search_datalake, self.button_search_nexar,
                                  self.button_all, self.button_none]

        self.image_labels = [self.label_image1, self.label_image2, self.label_image3, self.label_image4,
                             self.label_image5, self.label_image6, self.label_image7, self.label_image8]

        # Scale images automatically.
        for label in self.image_labels:
            label.setScaledContents(True)

        # Init properties used to indicate which directional arrows are turned on.
        self.direction_north = False
        self.direction_south = False
        self.direction_east = False
        self.direction_west = False
        self.direction_northwest = False
        self.direction_northeast = False
        self.direction_southwest = False
        self.direction_southeast = False

        # Init property used for Nexar auth token.
        self.auth_token = ""
        # Init empty dictionary for Nexar data.
        self.nexar_frames = {}
        # Init empty list for datalake rows.
        self.datalake_rows = []
        # Init property used to indicate which thumbnail is currently selected.
        self.currently_selected_image = 0
        # Init property assigned to full image display widget.
        self.ui = QtWidgets.QWidget()

        # Init display mode
        self.display_mode = 0
        # 0 = none
        # 1 = displaying datalake images
        # 2 = displaying nexar images

        # Init message log.
        self.plain_text_edit_log.clear()
        self.update_message_log("---------------------------------------------------------")
        self.update_message_log("Program started.")
        self.update_message_log("Nexar Image Tool - version " + __version__)
        self.update_message_log("---------------------------------------------------------")

        self.disable_image_buttons()

        self.refresh_token()
        self.get_auth_token()

    def process_full_image_display(self):
        # Used as a callback function of the display.py widget.
        pass

    def upload_to_s3(self, path, bucket, key):
        try:
            upload_file(path, bucket, key)  # Upload to s3
        except Exception as e:
            self.update_message_log(f"Upload to s3 failed: {e}")
        else:
            self.update_message_log(f"Upload to s3 succeeded.")

    def download_from_s3(self, path, bucket, key):

        try:
            download_file(path, bucket, key)
        except Exception as e:
            self.update_message_log(f"Download from s3 failed: {e}")
        else:
            self.update_message_log(f"Download from s3 succeeded.")

    @pyqtSlot(int)  # The parameter indicates that this slot will receive the new index as an integer
    def on_combo_coords_selection_changed(self, index):
        # Handle the selection change
        self.set_coords(index)

    def set_coords(self, index):
        # An index of zero indicates one line coords selected.
        # An index of one indicates two line coords selected.
        if index:
            # Display both lines, longitude and latitude.
            self.single_coords = False
            self.line_edit_latitude.show()
            self.label_latitude.show()
            self.label_longitude.show()
            self.line_edit_longitude.show()
            # Set default longitude, latitude
            self.line_edit_latitude.setText('33.98343972')
            self.line_edit_longitude.setText('-84.21422089')
        else:
            # Display only one line (using latitude line edit for single line).
            self.single_coords = True
            self.line_edit_latitude.show()
            self.label_latitude.hide()
            self.label_longitude.hide()
            self.line_edit_longitude.hide()
            # Set default longitude, latitude
            self.line_edit_latitude.setText('-84.21422089, 33.98343972')
            self.line_edit_longitude.setText('-84.21422089')

    @pyqtSlot()
    def on_button_download_image_clicked(self):
        self.download_image()

    def download_image(self):

        # This is effectively the download full image button

        if self.display_mode == 1:

            # Display datalake image. It was already downloaded as a thumbnail.
            image_number = self.currently_selected_image

            row = self.datalake_rows[image_number -1]

            s3_location = row[1]
            file = s3_location.split('/')[-1]
            path = 'datalake_images/' + file

            self.update_message_log(f"id: {row[0]}")
            self.update_message_log(f"s3_location: {row[1]}")
            self.update_message_log(f"asset_id: {row[2]}")
            self.update_message_log(f"processing_index: {row[3]}")
            self.update_message_log(f"long and lat: {row[4]}")
            self.update_message_log(f"datetime: {row[7]}")
            self.update_message_log(f"geom: {row[5]}")
            self.update_message_log(f"version: {row[6]}")
            self.update_message_log(f"vehicle_heading: {row[8]}")
            self.update_message_log(f"image_heading: {row[9]}")
            self.update_message_log(f"cam_id: {row[10]}")
            self.update_message_log("---------------------------------------------------------")

            # Launch widget to display image.
            self.window = QtWidgets.QWidget()
            # Pass path of image and display mode which indicates datalake or nexar.
            self.ui = Ui_Form(self.window, path, self.display_mode)
            # Define handler to process dialog content.
            # This callback function is not currently in use.
            # self.ui.submitted.connect(self.process_full_image_display())
            # Using showMaximized instead of show allows you to see the entire datalake image instead of a portion.
            # self.window.show()
            self.window.showMaximized()

        elif self.display_mode == 2:

            # Download nexar image.
            image_number = self.currently_selected_image
            frame = self.nexar_frames['frames'][image_number - 1]

            url = frame['frame_url']
            file = url.split('/')[-1]

            nexar_path = 'full_images/' + file
            datalake_path = 'datalake_images/' + file
            bucket = 'ushr-image/Nexar'
            key = file

            # Avoid downloading from Nexar if possible.
            # If the image has already been downloaded from Nexar or datalake, it will be in a local directory.
            # If it's not stored locally, try downloading from s3 bucket.
            # If it is not found in either of these locations, must resort to downloading from Nexar.
            if os.path.exists(datalake_path):
                self.update_message_log(f'Image previously downloaded: /datalake_images/{file}')
                path = datalake_path
            elif os.path.exists(nexar_path):
                self.update_message_log(f'Image previously downloaded: /full_images/{file}')
                path = nexar_path
            else:
                try:
                    # Download from datalake s3 bucket
                    download_file(datalake_path, bucket, key)
                    path = datalake_path
                    self.update_message_log(f'Image downloaded: /datalake_images/{file}')
                except Exception as ex:
                    # download full image from nexar
                    self.download_full_image(url)
                    path = nexar_path

            # Launch widget to display image.
            self.window = QtWidgets.QWidget()
            # Pass path of image and display mode which indicates datalake or nexar.
            self.ui = Ui_Form(self.window, path, self.display_mode)
            # Define handler to process dialog content.
            # This callback function is not currently in use.
            # self.ui.submitted.connect(self.process_full_image_display())
            # Using showMaximized instead of show matches what is done for datalake images.
            # self.window.show()
            self.window.showMaximized()

            # upload full image to s3
            self.upload_to_s3(path, bucket, key)

            image_number = self.currently_selected_image
            frame = self.nexar_frames['frames'][image_number - 1]
            captured_epoch = frame['captured_at']
            # convert from ms to s
            captured_epoch = float(captured_epoch/1000)

            captured_date_time = dt.fromtimestamp(captured_epoch)
            camera_heading = frame['camera_heading']

            # Calculate geom for DB entry.
            frame_id = frame['frame_id']
            latitude = float(frame['gps_info']['latitude'])
            longitude = float(frame['gps_info']['longitude'])
            captured_geom = geoalchemy2.shape.from_shape(shapely.geometry.Point((longitude, latitude)), srid=4326)

            # Assign other values for DB entry.
            s3_location = f"s3://{bucket}/{file}"
            # asset_id = None
            # processing_index = None
            geom = captured_geom
            # geom must be cast as a string
            geom = str(geom)
            version = f'nexar:{frame_id}'
            datetime = captured_date_time
            vehicle_heading = camera_heading
            vehicle_heading = round(float(vehicle_heading), 2) % 360
            # image_heading = None
            # cam_id = None

            self.update_message_log(f"Updating database if necessary.")
            self.update_message_log(f"s3_location: {s3_location}")
            self.update_message_log(f"geom: {geom}")
            self.update_message_log(f"version: {version}")
            self.update_message_log(f"datetime: {datetime}")
            self.update_message_log(f"vehicle_heading: {vehicle_heading}")
            self.update_message_log("---------------------------------------------------------")

            # Create and start a new thread to contain execution of the DB update.
            self.thread_update_DB = thread_updateDB()
            # Connect event handlers before starting the thread.
            self.thread_update_DB.finished.connect(self.evt_thread_updateDB_finished)
            self.thread_update_DB.thread_updateDB_status.connect(self.evt_thread_updateDB_status)
            # Assign properties of the new thread instance.
            self.thread_update_DB.s3_location = s3_location
            self.thread_update_DB.geom = geom
            self.thread_update_DB.version = version
            self.thread_update_DB.datetime = datetime
            self.thread_update_DB.vehicle_heading = vehicle_heading
            # Start the thread.
            self.thread_update_DB.start()

    def evt_thread_updateDB_status(self, status):
        # This event is used to update the message log with DB update progress.
        self.update_message_log(status)

    def evt_thread_updateDB_finished(self):
        # This event is used to update the message log when updating the DB exits.
        self.update_message_log("Closed thread updating database with Nexar image info.")
        self.update_message_log("---------------------------------------------------------")

    @pyqtSlot()
    def on_button_image1_clicked(self):
        self.button_image1_clicked()

    def button_image1_clicked(self):
        self.plain_text_edit_details.clear()
        self.currently_selected_image = 1
        self.display_image_info(self.currently_selected_image)
        self.deselect_image_buttons()
        self.button_image1.setStyleSheet('background-color: green')
        self.button_download_image.setEnabled(True)
        self.button_download_image.setStyleSheet('background-color: red')

    @pyqtSlot()
    def on_button_image2_clicked(self):
        self.button_image2_clicked()

    def button_image2_clicked(self):
        self.plain_text_edit_details.clear()
        self.currently_selected_image = 2
        self.display_image_info(self.currently_selected_image)
        self.deselect_image_buttons()
        self.button_image2.setStyleSheet('background-color: green')
        self.button_download_image.setEnabled(True)
        self.button_download_image.setStyleSheet('background-color: red')

    @pyqtSlot()
    def on_button_image3_clicked(self):
        self.button_image3_clicked()

    def button_image3_clicked(self):
        self.plain_text_edit_details.clear()
        self.currently_selected_image = 3
        self.display_image_info(self.currently_selected_image)
        self.deselect_image_buttons()
        self.button_image3.setStyleSheet('background-color: green')
        self.button_download_image.setEnabled(True)
        self.button_download_image.setStyleSheet('background-color: red')

    @pyqtSlot()
    def on_button_image4_clicked(self):
        self.button_image4_clicked()

    def button_image4_clicked(self):
        self.plain_text_edit_details.clear()
        self.currently_selected_image = 4
        self.display_image_info(self.currently_selected_image)
        self.deselect_image_buttons()
        self.button_image4.setStyleSheet('background-color: green')
        self.button_download_image.setEnabled(True)
        self.button_download_image.setStyleSheet('background-color: red')

    @pyqtSlot()
    def on_button_image5_clicked(self):
        self.button_image5_clicked()

    def button_image5_clicked(self):
        self.plain_text_edit_details.clear()
        self.currently_selected_image = 5
        self.display_image_info(self.currently_selected_image)
        self.deselect_image_buttons()
        self.button_image5.setStyleSheet('background-color: green')
        self.button_download_image.setEnabled(True)
        self.button_download_image.setStyleSheet('background-color: red')

    @pyqtSlot()
    def on_button_image6_clicked(self):
        self.button_image6_clicked()

    def button_image6_clicked(self):
        self.plain_text_edit_details.clear()
        self.currently_selected_image = 6
        self.display_image_info(self.currently_selected_image)
        self.deselect_image_buttons()
        self.button_image6.setStyleSheet('background-color: green')
        self.button_download_image.setEnabled(True)
        self.button_download_image.setStyleSheet('background-color: red')

    @pyqtSlot()
    def on_button_image7_clicked(self):
        self.button_image7_clicked()

    def button_image7_clicked(self):
        self.plain_text_edit_details.clear()
        self.currently_selected_image = 7
        self.display_image_info(self.currently_selected_image)
        self.deselect_image_buttons()
        self.button_image7.setStyleSheet('background-color: green')
        self.button_download_image.setEnabled(True)
        self.button_download_image.setStyleSheet('background-color: red')

    @pyqtSlot()
    def on_button_image8_clicked(self):
        self.button_image8_clicked()

    def button_image8_clicked(self):
        self.plain_text_edit_details.clear()
        self.currently_selected_image = 8
        self.display_image_info(self.currently_selected_image)
        self.deselect_image_buttons()
        self.button_image8.setStyleSheet('background-color: green')
        self.button_download_image.setEnabled(True)
        self.button_download_image.setStyleSheet('background-color: red')

    def resize_image(self, input_image_path, output_image_path, size):
        """
        Resize an image to the specified size.

        Parameters:
        - input_image_path: str, the path to the input image.
        - output_image_path: str, the path where the resized image will be saved.
        - size: tuple, the desired size in pixels as (width, height).
        """
        with Image.open(input_image_path) as image:
            # Resize the image
            resized_image = image.resize(size, Image.ANTIALIAS)
            # Save the resized image
            resized_image.save(output_image_path)

    def display_image_info(self, image_number):

        if self.display_mode == 1:
            # Display datalake images
            rows = self.datalake_rows
            row = rows[image_number - 1]

            self.plain_text_edit_details.appendPlainText(f"id: {row[0]}")
            self.plain_text_edit_details.appendPlainText(f"s3_location: {row[1]}")
            self.plain_text_edit_details.appendPlainText(f"asset_id: {row[2]}")
            self.plain_text_edit_details.appendPlainText(f"processing_index: {row[3]}")
            self.plain_text_edit_details.appendPlainText(f"long and lat: {row[4]}")
            self.plain_text_edit_details.appendPlainText(f"datetime: {row[7]}")
            self.plain_text_edit_details.appendPlainText(f"geom: {row[5]}")
            self.plain_text_edit_details.appendPlainText(f"version: {row[6]}")
            self.plain_text_edit_details.appendPlainText(f"vehicle_heading: {row[8]}")
            self.plain_text_edit_details.appendPlainText(f"image_heading: {row[9]}")
            self.plain_text_edit_details.appendPlainText(f"cam_id: {row[10]}")


        elif self.display_mode == 2:
            # Display nexar images
            frame = self.nexar_frames['frames'][image_number - 1]
            captured_epoch = frame['captured_at']
            # convert from ms to s
            captured_epoch = float(captured_epoch / 1000)
            # print(f'captured_epoch: {captured_epoch}')
            # print(type(captured_epoch))
            captured_date_time = dt.fromtimestamp(captured_epoch)

            self.plain_text_edit_details.appendPlainText(f"frame_id: {frame['frame_id']}")
            self.plain_text_edit_details.appendPlainText(f"latitude: {frame['gps_info']['latitude']}")
            self.plain_text_edit_details.appendPlainText(f"longitude: {frame['gps_info']['longitude']}")
            self.plain_text_edit_details.appendPlainText(f"direction: {frame['direction']}")
            self.plain_text_edit_details.appendPlainText(f"captured_epoch: {frame['captured_at']}")
            self.plain_text_edit_details.appendPlainText(f"captured_date_time: {captured_date_time}")
            self.plain_text_edit_details.appendPlainText(f"camera_heading: {frame['camera_heading']}")
            self.plain_text_edit_details.appendPlainText(f"frame_quality: {frame['frame_quality']}")
            self.plain_text_edit_details.appendPlainText(f"frame_context: {frame['frame_context']}")
            self.plain_text_edit_details.appendPlainText(f"thumbnail_url: {frame['thumbnail_url']}")
            self.plain_text_edit_details.appendPlainText(f"frame_url: {frame['frame_url']}")

    def deselect_image_buttons(self):

        for button in self.image_buttons:
            button.setStyleSheet('background-color: rgb(134, 134, 134)')

    @pyqtSlot()
    def on_button_north_clicked(self):
        self.north_clicked()

    def north_clicked(self):
        if self.direction_north:
            self.direction_north = False
            self.button_north.setStyleSheet('background-color: rgb(134, 134, 134)')
        else:
            self.direction_north = True
            self.button_north.setStyleSheet('background-color: green')

    @pyqtSlot()
    def on_button_south_clicked(self):
        self.south_clicked()

    def south_clicked(self):
        if self.direction_south:
            self.direction_south = False
            self.button_south.setStyleSheet('background-color: rgb(134, 134, 134)')
        else:
            self.direction_south = True
            self.button_south.setStyleSheet('background-color: green')

    @pyqtSlot()
    def on_button_east_clicked(self):
        self.east_clicked()

    def east_clicked(self):
        if self.direction_east:
            self.direction_east = False
            self.button_east.setStyleSheet('background-color: rgb(134, 134, 134)')
        else:
            self.direction_east = True
            self.button_east.setStyleSheet('background-color: green')

    @pyqtSlot()
    def on_button_west_clicked(self):
        self.west_clicked()

    def west_clicked(self):
        if self.direction_west:
            self.direction_west = False
            self.button_west.setStyleSheet('background-color: rgb(134, 134, 134)')
        else:
            self.direction_west = True
            self.button_west.setStyleSheet('background-color: green')

    @pyqtSlot()
    def on_button_northwest_clicked(self):
        self.northwest_clicked()

    def northwest_clicked(self):
        if self.direction_northwest:
            self.direction_northwest = False
            self.button_northwest.setStyleSheet('background-color: rgb(134, 134, 134)')
        else:
            self.direction_northwest = True
            self.button_northwest.setStyleSheet('background-color: green')

    @pyqtSlot()
    def on_button_northeast_clicked(self):
        self.northeast_clicked()

    def northeast_clicked(self):
        if self.direction_northeast:
            self.direction_northeast = False
            self.button_northeast.setStyleSheet('background-color: rgb(134, 134, 134)')
        else:
            self.direction_northeast = True
            self.button_northeast.setStyleSheet('background-color: green')

    @pyqtSlot()
    def on_button_southwest_clicked(self):
        self.southwest_clicked()

    def southwest_clicked(self):
        if self.direction_southwest:
            self.direction_southwest = False
            self.button_southwest.setStyleSheet('background-color: rgb(134, 134, 134)')
        else:
            self.direction_southwest = True
            self.button_southwest.setStyleSheet('background-color: green')

    @pyqtSlot()
    def on_button_southeast_clicked(self):
        self.southeast_clicked()

    def southeast_clicked(self):
        if self.direction_southeast:
            self.direction_southeast = False
            self.button_southeast.setStyleSheet('background-color: rgb(134, 134, 134)')
        else:
            self.direction_southeast = True
            self.button_southeast.setStyleSheet('background-color: green')

    @pyqtSlot()
    def on_button_all_clicked(self):
        self.all_clicked()

    def all_clicked(self):

        # Set backcolor of directional buttons to gray (i.e. unselected)
        for button in self.direction_buttons:
            button.setStyleSheet('background-color: green')

        # Set all directional flags to false (i.e. unselected)
        self.direction_north = True
        self.direction_south = True
        self.direction_east = True
        self.direction_west = True
        self.direction_northwest = True
        self.direction_northeast = True
        self.direction_southwest = True
        self.direction_southeast = True

    @pyqtSlot()
    def on_button_none_clicked(self):
        self.none_clicked()

    def none_clicked(self):

        # Set backcolor of directional buttons to gray (i.e. unselected)
        for button in self.direction_buttons:
            button.setStyleSheet('background-color: rgb(134, 134, 134)')

        # Set all directional flags to false (i.e. unselected)
        self.direction_north = False
        self.direction_south = False
        self.direction_east = False
        self.direction_west = False
        self.direction_northwest = False
        self.direction_northeast = False
        self.direction_southwest = False
        self.direction_southeast = False

    def validate_coords(self):
        # Initial values
        latitude = 0
        longitude = 0
        radius_degrees = 0
        error = False
        error_msg = "No errors."
        coords_first = 0
        coords_second = 0

        # Get coordinates input by user, and set an error code if invalid.
        if self.single_coords:
            coords = self.line_edit_latitude.text()
            if "," in coords:
                coords_first = coords.split(',')[0]
                coords_second = coords.split(',')[1]
            elif " " in coords:
                coords_first = coords.split(' ')[0]
                coords_second = coords.split(' ')[1]
            else:
                error_msg = "Invalid coordinates. Values must be separated by a space or comma."
                error = True

            # Continue validating coordinates only if error free so far.
            if not error:
                try:
                    coords_first = float(coords_first)
                    coords_second = float(coords_second)
                except Exception as ex:
                    error_msg = "Invalid coordinates. Must be numeric."
                    error = True

            # Continue validating coordinates only if error free so far.
            if not error:
                # Ensure that one coord is positive and the other is negative.
                if coords_first < 0:
                    if coords_second <= 0:
                        error_msg = "Latitude is invalid. Only North America is supported. " \
                                    "Expecting coordinates in the northern hemisphere (i.e. positive latitude) " \
                                    "and west of the Prime Meridian, which is degrees West " \
                                    "(typically indicated as negative longitude)."
                        error = True
                    else:
                        latitude = coords_second
                        longitude = coords_first
                else:
                    if coords_second >= 0:
                        error_msg = "Longitude is invalid. Only North America is supported. " \
                                    "Expecting coordinates in the northern hemisphere (i.e. positive latitude) " \
                                    "and west of the Prime Meridian, which is degrees West " \
                                    "(typically indicated as negative longitude)."
                        error = True
                    else:
                        latitude = coords_first
                        longitude = coords_second
        else:
            latitude = self.line_edit_latitude.text()
            longitude = self.line_edit_longitude.text()
            try:
                latitude = float(latitude)
                longitude = float(longitude)
            except Exception as ex:
                error_msg = "Invalid coordinates. Must be numeric."
                error = True

            # Continue validating coordinates only if error free so far.
            if not error:
                if latitude <= 0:
                    error_msg = "Latitude is invalid. Only North America is supported. " \
                                    "Expecting coordinates in the northern hemisphere (i.e. positive latitude) " \
                                    "and west of the Prime Meridian, which is degrees West " \
                                    "(typically indicated as negative longitude)."
                    error = True

            # Continue validating coordinates only if error free so far.
            if not error:
                if longitude >= 0:
                    error_msg = "Longitude is invalid. Only North America is supported. " \
                                    "Expecting coordinates in the northern hemisphere (i.e. positive latitude) " \
                                    "and west of the Prime Meridian, which is degrees West " \
                                    "(typically indicated as negative longitude)."
                    error = True

        # Continue validating coordinates only if error free so far.
        if not error:
            try:
                radius = self.line_edit_radius.text()
                radius = float(radius)
                radius_degrees = float(radius / METERS_PER_DEGREE)
                radius_degrees = round(float(radius_degrees), 4)

            except Exception as ex:
                error_msg = "Invalid search radius. Must be numeric."
                error = True

        return latitude, longitude, radius_degrees, error, error_msg

    @pyqtSlot()
    def on_button_search_datalake_clicked(self):
        self.search_datalake()

    def search_datalake(self):

        # Set display mode to datalake
        self.display_mode = 1

        # Clear thumbnail images, which are the results of last nexar search, if any.
        self.clear_thumbnail_images()
        self.deselect_image_buttons()
        self.plain_text_edit_details.clear()
        self.currently_selected_image = 0

        self.disable_image_buttons()
        self.disable_interface_buttons()

        # log.warning(f'in search_datalake function')

        # Validate user inputs including coordinates and search radius.
        latitude, longitude, radius_degrees, error, error_msg = self.validate_coords()
        if error:
            self.update_message_log(error_msg)
            self.enable_interface_buttons()
            return

        self.update_message_log(f"Searching Datalake ...")

        # Create and start a new thread to contain execution of the Datalake search.
        self.thread_search_datalake = thread_search_datalake()
        # Connect event handlers before starting the thread.
        self.thread_search_datalake.finished.connect(self.evt_thread_search_datalake_finished)
        self.thread_search_datalake.thread_search_datalake_status.connect(self.evt_thread_search_datalake_status)
        self.thread_search_datalake.thread_search_datalake_rows.connect(self.evt_thread_search_datalake_rows)
        # Assign properties of the new thread instance.
        self.thread_search_datalake.latitude = latitude
        self.thread_search_datalake.longitude = longitude
        self.thread_search_datalake.radius_degrees = radius_degrees
        self.thread_search_datalake.image_buttons = self.image_buttons
        self.thread_search_datalake.image_labels = self.image_labels
        self.thread_search_datalake.interface_buttons = self.interface_buttons
        self.thread_search_datalake.direction_buttons = self.direction_buttons

        # Start the thread.
        self.thread_search_datalake.start()

    def evt_thread_search_datalake_rows(self, rows):
        # This event is used to pass the datalake query results to the main application.
        self.datalake_rows = rows

    def evt_thread_search_datalake_status(self, status):
        # This event is used to update the message log with datalake search progress.
        self.update_message_log(status)

    def evt_thread_search_datalake_finished(self):
        # This event is used to update the message log when searching datalake exits.
        self.update_message_log("Closed thread searching Datalake.")
        self.update_message_log("---------------------------------------------------------")

    @pyqtSlot()
    def on_button_search_nexar_clicked(self):
        self.search_nexar()

    def search_nexar(self):

        # Set display mode to nexar
        self.display_mode = 2

        # Clear thumbnail images, to prepare for results of this new nexar search.
        # This protects against the scenario where
        # more thumbnails were populated in previous search than in current search.
        self.clear_thumbnail_images()
        self.deselect_image_buttons()
        self.plain_text_edit_details.clear()
        self.currently_selected_image = 0

        # These two function calls are only useful if run in a separate thread.
        # The intent is to disable buttons after search is started,
        # then re-enable when search is complete.
        self.disable_image_buttons()
        self.disable_interface_buttons()

        # Validate user inputs including coordinates and search radius.
        latitude, longitude, radius_degrees, error, error_msg = self.validate_coords()
        if error:
            self.update_message_log(error_msg)
            self.enable_interface_buttons()
            return

        self.update_message_log(f"Searching Nexar ...")

        # Create and start a new thread to contain execution of the Nexar search.
        self.thread_search_nexar = thread_search_nexar()
        # Connect event handlers before starting the thread.
        self.thread_search_nexar.finished.connect(self.evt_thread_search_nexar_finished)
        self.thread_search_nexar.thread_search_nexar_status.connect(self.evt_thread_search_nexar_status)
        self.thread_search_nexar.thread_search_nexar_frames.connect(self.evt_thread_search_nexar_frames)
        # Assign properties of the new thread instance.
        self.thread_search_nexar.latitude = latitude
        self.thread_search_nexar.longitude = longitude
        self.thread_search_nexar.radius_degrees = radius_degrees
        self.thread_search_nexar.image_buttons = self.image_buttons
        self.thread_search_nexar.image_labels = self.image_labels
        self.thread_search_nexar.direction_north = self.direction_north
        self.thread_search_nexar.direction_south = self.direction_south
        self.thread_search_nexar.direction_east = self.direction_east
        self.thread_search_nexar.direction_west = self.direction_west
        self.thread_search_nexar.direction_northwest = self.direction_northwest
        self.thread_search_nexar.direction_northeast = self.direction_northeast
        self.thread_search_nexar.direction_southwest = self.direction_southwest
        self.thread_search_nexar.direction_southeast = self.direction_southeast
        self.thread_search_nexar.interface_buttons = self.interface_buttons
        self.thread_search_nexar.auth_token = self.auth_token
        self.thread_search_nexar.direction_buttons = self.direction_buttons

        # Start the thread.
        self.thread_search_nexar.start()

    def evt_thread_search_nexar_frames(self, data):
        # This event is used to pass the nexar results to the main application.
        self.nexar_frames = data

    def evt_thread_search_nexar_status(self, status):
        # This event is used to update the message log with nexar search progress.
        self.update_message_log(status)

    def evt_thread_search_nexar_finished(self):
        # This event is used to update the message log when searching nexar exits.
        self.update_message_log("Closed thread searching Nexar.")
        self.update_message_log("---------------------------------------------------------")

    def clear_thumbnail_images(self):

        for label in self.image_labels:
            label.setPixmap(QtGui.QPixmap('blank.png'))

    def update_message_log(self, msg):
        date_now = QDate.currentDate().toString(Qt.ISODate)
        time_now = QTime.currentTime().toString(Qt.ISODateWithMs)
        log_entry = str("::" + date_now + "::" + time_now + ": " + msg)
        self.plain_text_edit_log.appendPlainText(log_entry)
        # Now ensure the cursor is visible, which will scroll to the bottom
        self.plain_text_edit_log.ensureCursorVisible()
        # Move the horizontal scroll bar to the left
        horizontal_scroll_bar = self.plain_text_edit_log.horizontalScrollBar()
        horizontal_scroll_bar.setValue(horizontal_scroll_bar.minimum())

    def enable_interface_buttons(self):

        for button in self.interface_buttons:
            button.setEnabled(True)

        for button in self.direction_buttons:
            button.setEnabled(True)

    def disable_interface_buttons(self):

        for button in self.interface_buttons:
            button.setEnabled(False)

        for button in self.direction_buttons:
            button.setEnabled(False)

    def disable_image_buttons(self):

        self.button_download_image.setEnabled(False)
        self.button_download_image.setStyleSheet('background-color: rgb(134, 134, 134)')

        for button in self.image_buttons:
            button.setEnabled(False)

    def download_full_image(self, url):

        # Ensure the image directory exists
        os.makedirs("full_images", exist_ok=True)

        headers = {
            'Authorization': 'Bearer ' + self.auth_token,
        }

        response = requests.get(url, headers=headers,)
        file = url.split('/')[-1]

        with open('full_images/' + file, 'wb') as f:
            f.write(response.content)

        self.update_message_log(f'Image downloaded: /full_images/{file}')

    def refresh_token(self):

        refresh_token = creds.refresh_token
        response = requests.post('https://external.getnexar.com/dev-portal/refresh-token',
                                 headers={'content-type': 'application/x-www-form-urlencoded'},
                                 data={'refresh_token': refresh_token}
                                 )

        # close the connection
        response.close()

        # convert response to a python dictionary.
        data = response.json()

        # dump a python object into a json string
        new_string = json.dumps(data, indent=2)
        token_type = data['token_type']
        access_token = data['access_token']

        # write to json file
        with open("auth_token.json", "w") as f:
            f.write(new_string)

    def get_auth_token(self):

        # Get auth token from file.
        with open("auth_token.json", "r") as f:
            data = json.load(f)

        self.auth_token = data['access_token']


class thread_updateDB(QThread):
    """
    This is a thread to update the database with nexar image info.
    """

    # Properties assigned by the calling process.
    s3_location = None
    geom = None
    version = None
    datetime = None
    vehicle_heading = None

    # Create a custom signal to notify main application of status.
    thread_updateDB_status = pyqtSignal(str)

    def run(self):

        try:
            msg = "Started thread to update database with Nexar image info."
            self.thread_updateDB_status.emit(msg)

            db_region = 'north_america'
            with ushr.acorn.datalake.utils.connect_to_db(db_region) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    INSERT INTO datalake.camera_image (s3_location, geom, version, datetime, vehicle_heading)
                    VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""", (self.s3_location, self.geom, self.version, self.datetime, self.vehicle_heading,))

        except Exception as e:
            msg = "Experienced an error updating the database with Nexar image info; ", str(e)
        else:
            msg = "Updated the database with Nexar image info, with no errors."

        # Send message to main thread.
        self.thread_updateDB_status.emit(msg)


class thread_search_datalake(QThread):
    """
    This is a thread to access the database, searching for datalake image info.
    """

    # Properties assigned by the calling process.
    # These properties are assigned the value of the MainWindow properties by the same name.
    longitude = None
    latitude = None
    radius_degrees = None
    image_buttons = []
    image_labels = []
    interface_buttons = []
    direction_buttons = []

    # Create a custom signal to notify main application of status.
    thread_search_datalake_status = pyqtSignal(str)
    # Create a custom signal to pass query results to main application.
    thread_search_datalake_rows = pyqtSignal(list)

    def run(self):

        try:
            msg = "Started thread to search Datalake."
            self.thread_search_datalake_status.emit(msg)

            db_region = 'north_america'
            with ushr.acorn.datalake.utils.connect_to_db(db_region) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(""" SELECT id, s3_location, asset_id, processing_index, st_astext(geom), geom, version, datetime, vehicle_heading, image_heading, cam_id 
                    FROM datalake.camera_image
                    WHERE st_dwithin(ST_SetSRID(ST_Point(%s, %s),4326),geom,%s)""",
                                   (self.longitude, self.latitude, self.radius_degrees,))
                    rows = cursor.fetchall()
                    if rows:
                        self.thread_search_datalake_rows.emit(rows)

                        # Ensure the image directory exists
                        os.makedirs("datalake_images", exist_ok=True)

                        for index, row in enumerate(rows, start=1):
                            if index <= len(self.image_buttons):

                                s3_location = row[1]
                                file = s3_location.split('/')[-1]
                                path = 'datalake_images/' + file
                                if s3_location.split('/')[-2] == 'Nexar':
                                    bucket = 'ushr-image/Nexar'
                                else:
                                    bucket = 'ushr-image'
                                key = file

                                # Download the file from s3 if not already downloaded.
                                if os.path.exists(path):
                                    msg = f'Image previously downloaded: /datalake_images/{file}'
                                    self.thread_search_datalake_status.emit(msg)
                                else:
                                    self.download_from_s3(path, bucket, key)
                                    msg = f'Image downloaded: /datalake_images/{file}'
                                    self.thread_search_datalake_status.emit(msg)

                                self.image_buttons[index - 1].setEnabled(True)

                                # Load an image and scale it (keeping aspect ratio)
                                # pixmap = QtGui.QPixmap(path).scaled(480, 270, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                # No need to scale it. The QSizePolicy below allows us to work with full res image.
                                pixmap = QtGui.QPixmap(path)
                                # Set the scaled pixmap to the label
                                self.image_labels[index - 1].setPixmap(pixmap)
                                # Set the alignment to center (if the label is larger than the pixmap)
                                self.image_labels[index - 1].setAlignment(Qt.AlignCenter)
                                # Adjust the size policy to allow shrinking smaller than the pixmap
                                self.image_labels[index - 1].setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
                                # Set the label to scale the pixmap accordingly
                                self.image_labels[index - 1].setScaledContents(True)

                    else:
                        msg = 'No matching images.'
                        self.thread_search_datalake_status.emit(msg)

        except Exception as e:
            msg = f"Experienced an error searching Datalake; {e}"
        else:
            msg = "Searched Datalake with no errors."

        # Send message to main thread.
        self.thread_search_datalake_status.emit(msg)
        self.enable_interface_buttons()

    def download_from_s3(self, path, bucket, key):

        try:
            download_file(path, bucket, key)
        except Exception as e:
            msg = f"Download from s3 failed: {e}"
            self.thread_search_datalake_status.emit(msg)
        else:
            msg = f"Download from s3 succeeded."
            self.thread_search_datalake_status.emit(msg)

    def enable_interface_buttons(self):

        for button in self.interface_buttons:
            button.setEnabled(True)

        for button in self.direction_buttons:
            button.setEnabled(True)


class thread_search_nexar(QThread):
    """
    This is a thread to access nexar's API.
    """

    # Properties assigned by the calling process.
    # These properties are assigned the value of the MainWindow properties by the same name.
    longitude = None
    latitude = None
    radius_degrees = None
    image_buttons = []
    image_labels = []
    direction_north = None
    direction_south = None
    direction_east = None
    direction_west = None
    direction_northwest = None
    direction_northeast = None
    direction_southwest = None
    direction_southeast = None
    interface_buttons = []
    auth_token = None
    direction_buttons = []

    # Create a custom signal to notify main application of status.
    thread_search_nexar_status = pyqtSignal(str)
    # Create a custom signal to pass search results to main application.
    thread_search_nexar_frames = pyqtSignal(dict)

    def run(self):

        try:
            msg = "Started thread to search Nexar."
            self.thread_search_nexar_status.emit(msg)

            sw_latitude = self.latitude - self.radius_degrees
            sw_longitude = self.longitude - self.radius_degrees

            ne_latitude = self.latitude + self.radius_degrees
            ne_longitude = self.longitude + self.radius_degrees

            headers = {
                'accept': 'application/json',
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + self.auth_token,
            }
            # start and end time are epoch ms
            # Using a start_time of 1/1/2014
            start_time = 1388534400000
            # Calculate end_time of current day in seconds
            end_time = int(time.time())
            # Convert to ms
            end_time = end_time * 1000

            json_data = {
              "bounding_box": {
                "south_west": {
                  "longitude": -84.22322089000001,
                  "latitude": 33.97443972
                },
                "north_east": {
                  "longitude": -84.20522089,
                  "latitude": 33.99243972
                }
              },
              "filters": {
                "min_frame_quality": 0.7,
                "road_types": [
                    "MOTORWAY",
                    "TRUNK",
                    "PRIMARY",
                    "SECONDARY",
                    "TERTIARY",
                    "UNCLASSIFIED",
                    "RESIDENTIAL",
                    "SERVICE",
                    "MOTORWAY_LINK",
                    "TRUNK_LINK",
                    "PRIMARY_LINK",
                    "SECONDARY_LINK",
                    "TERTIARY_LINK"
                ],
                "directions": [

                ],
                "frames_context": [
                  "DAYLIGHT",
                  "NIGHTTIME"
                ],
                "start_time": start_time,
                "end_time": end_time
              },
              "sort_by": "TIMESTAMP"
            }

            # Add directions to the request.
            if self.direction_north:
                json_data['filters']['directions'].append("NORTH")
            if self.direction_south:
                json_data['filters']['directions'].append("SOUTH")
            if self.direction_east:
                json_data['filters']['directions'].append("EAST")
            if self.direction_west:
                json_data['filters']['directions'].append("WEST")
            if self.direction_northwest:
                json_data['filters']['directions'].append("NORTH_WEST")
            if self.direction_northeast:
                json_data['filters']['directions'].append("NORTH_EAST")
            if self.direction_southwest:
                json_data['filters']['directions'].append("SOUTH_WEST")
            if self.direction_southeast:
                json_data['filters']['directions'].append("SOUTH_EAST")

            directions = json_data['filters']['directions']
            if len(directions) == 0:
                error_msg = 'No matching images. Please select one or more directions.'
                print(error_msg)
                self.thread_search_nexar_status.emit(error_msg)
                self.enable_interface_buttons()
                return

            json_data['bounding_box']['south_west']['latitude'] = sw_latitude
            json_data['bounding_box']['south_west']['longitude'] = sw_longitude
            json_data['bounding_box']['north_east']['latitude'] = ne_latitude
            json_data['bounding_box']['north_east']['longitude'] = ne_longitude

            response = requests.post('https://external.getnexar.com/api/virtualcam/v4/frames', headers=headers, json=json_data)

            # convert response to a python dictionary.
            data = response.json()

            # dump a python object into a json string
            new_string = json.dumps(data, indent=2)

            # write to json file
            with open("data.json", "w") as f:
                f.write(new_string)

            f.close()

            # read from json file
            with open("data.json", "r") as f:
                data = json.load(f)

            self.thread_search_nexar_frames.emit(data)

            try:
                for index, frame in enumerate(data['frames'], start=1):
                    url = frame['thumbnail_url']

                    if index <= len(self.image_buttons):
                        self.image_buttons[index - 1].setEnabled(True)  # Enabled the button at the current index
                        self.download_thumbnail(url, index)

            except Exception as ex:
                error_msg = 'No matching images.'
                self.thread_search_nexar_status.emit(error_msg)

            self.enable_interface_buttons()

        except Exception as e:
            msg = f"Experienced an error searching Nexar API; {e}"
        else:
            msg = "Searched Nexar API with no errors."

        # Send message to main thread.
        self.thread_search_nexar_status.emit(msg)

    def download_thumbnail(self, url, index):

        headers = {
            'Authorization': 'Bearer ' + self.auth_token,
        }

        # Ensure the thumbnails directory exists
        os.makedirs("thumbnails", exist_ok=True)

        response = requests.get(url, headers=headers, )
        file = url.split('/')[-1]

        with open('thumbnails/' + file, 'wb') as f:
            f.write(response.content)

        # Load an image.
        pixmap = QtGui.QPixmap('thumbnails/' + file)
        # Set the pixmap to the label
        self.image_labels[index - 1].setPixmap(pixmap)
        # Set the alignment to center (if the label is larger than the pixmap)
        self.image_labels[index - 1].setAlignment(Qt.AlignCenter)
        # Adjust the size policy to allow shrinking smaller than the pixmap
        self.image_labels[index - 1].setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        # Set the label to scale the pixmap accordingly
        self.image_labels[index - 1].setScaledContents(True)

        msg = f'Image downloaded: /thumbnails/{file}'
        self.thread_search_nexar_status.emit(msg)

    def enable_interface_buttons(self):

        for button in self.interface_buttons:
            button.setEnabled(True)

        for button in self.direction_buttons:
            button.setEnabled(True)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    ui = MainWindow()
    ui.show()
    sys.exit(app.exec_())


