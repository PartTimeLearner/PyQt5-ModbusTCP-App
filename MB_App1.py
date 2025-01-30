from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import QTableWidgetItem
from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
import time
import mysql.connector
from mysql.connector import Error
import struct
from pyModbusTCP.client import ModbusClient
import json
from PyQt5 import QtCore
import struct
import paho.mqtt.client as mqtt

class MQTTThread(QtCore.QThread):
    def __init__(self, mqtt_client, topic_prefix, broker, port_mqtt, parent=None):
        super(MQTTThread, self).__init__(parent)
        self.client = mqtt_client
        self.topic_prefix = topic_prefix
        self.broker = broker
        self.port_mqtt = port_mqtt

    def publish(self, topic, message):
        try:
            self.client.publish(f"{self.topic_prefix}", message)
            print(f"Published to {self.topic_prefix}: {message}")
        except Exception as e:
            print(self.client)
            print(self.topic_prefix)
            print(f"Error publishing to MQTT: {e}")
    
    def stop_pub(self):
        self.client.disconnect()  

class DatabaseHandler(QtCore.QThread):
    def __init__(self, host, user, password, database, table_name, parent = None):
        super(DatabaseHandler,self).__init__(parent)
        self.connection = None
        self.table_name = table_name
        try:
            self.connection = mysql.connector.connect(
                host=host,
                user=user,
                password=password,
                database=database
            )
            self.cursor = self.connection.cursor()
            print("Database connection established.")
        except Error as e:
            print(f"Error connecting to database: {e}")

    def save_json(self, json_data):
        """
        Simpan data JSON dinamis ke database.
        :param json_data: Dictionary JSON dengan struktur seperti {"int": {...}, "float": {...}}
        """
        try:
            # Gabungkan semua data dari int dan float menjadi satu dictionary
            combined_data = {**json_data.get("int", {}), **json_data.get("float", {})}

            # Membuat query dinamis berdasarkan data JSON
            columns = ', '.join(combined_data.keys())
            placeholders = ', '.join(['%s'] * len(combined_data))
            query = f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE "
            query += ', '.join([f"{col} = VALUES({col})" for col in combined_data.keys()])

            values = list(combined_data.values())
            self.cursor.execute(query, values)
            self.connection.commit()
            print(f"Data saved to table {self.table_name}: {combined_data}")
        except Error as e:
            print(f"Error saving JSON data to table {self.table_name}: {e}")

    def close(self):
        if self.connection:
            self.cursor.close()
            self.connection.close()
            print("Database connection closed.")

class ModbusTCP_Worker(QtCore.QThread):
    data_ready = QtCore.pyqtSignal(str)  # Signal untuk JSON data
    int_update = QtCore.pyqtSignal(int, int, int)
    float_update = QtCore.pyqtSignal(int, int, float)

    def __init__(self, modbus_client, tableWidget, tableWidget_2, mqtt_thread, db_handler, time_up,parent=None):
        super(ModbusTCP_Worker, self).__init__(parent)
        self.client = modbus_client
        self.mqtt_thread = mqtt_thread
        self.run_worker = False  # Flag untuk mengontrol loop
        self.tableWidget = tableWidget
        self.tableWidget_2 = tableWidget_2
        self.data = {"int": {}, "float": {}}  # Struktur data untuk JSON
        self.is_stopping = False  # Flag untuk melacak proses penghentian thread
        self.db_handler = db_handler
        self.time_up = time_up
        self.ui = ui

    def run(self):
        """Override fungsi run untuk memulai loop pembacaan."""
        print("Thread started.")
        self.read_modbus_variables()

    def read_modbus_variables(self):
        while self.run_worker:
            rows_int = self.tableWidget.rowCount()
            for self.row1 in range(rows_int):
                if self.is_stopping:
                    print("Stopping read_modbus_variables (int)...")
                    return
                reg = self.tableWidget.item(self.row1, 0).text() if self.tableWidget.item(self.row1, 0) else None
                variable = self.tableWidget.item(self.row1, 1).text() if self.tableWidget.item(self.row1, 1) else None

                if not reg or not reg.isdigit():
                    continue

                reg_int = int(reg)
                try:
                    self.value1 = self.read_int(self.client, reg_int, 1)
                    if variable:
                        self.int_update.emit(self.row1, 2, self.value1)
                        self.data["int"][variable] = self.value1

                except Exception as e:
                    print(f"Error reading Modbus register {reg_int} (int): {e}")

            rows_float = self.tableWidget_2.rowCount()
            for self.row2 in range(rows_float):
                if self.is_stopping:
                    print("Stopping read_modbus_variables (float)...")
                    return
                reg = self.tableWidget_2.item(self.row2, 0).text() if self.tableWidget_2.item(self.row2, 0) else None
                variable = self.tableWidget_2.item(self.row2, 1).text() if self.tableWidget_2.item(self.row2, 1) else None

                if not reg or not reg.isdigit():
                    continue

                reg_int = int(reg)
                try:
                    self.value2 = self.read_float(self.client, reg_int)
                    if variable:
                        self.float_update.emit(self.row2, 2, self.value2)
                        self.data["float"][variable] = self.value2

                except Exception as e:
                    print(f"Error reading Modbus register {reg_int} (float): {e}")

            try:
                json_data = json.dumps(self.data)
                print(f"Generated JSON: {json_data}")

                if not self.ui.mqtt_update_checkBox.isChecked() and not self.ui.database_checkBox.isChecked():
                    print("Modbus TCP Only")
                elif self.ui.mqtt_update_checkBox.isChecked() and not self.ui.database_checkBox.isChecked():
                    self.mqtt_thread.publish("modbus_data", json_data)
                        
                elif not self.ui.mqtt_update_checkBox.isChecked() and self.ui.database_checkBox.isChecked():
                    json_data_dict = json.loads(json_data)
                    self.db_handler.save_json(json_data_dict)
                                
                elif self.ui.mqtt_update_checkBox.isChecked() and self.ui.database_checkBox.isChecked():
                    self.mqtt_thread.publish("modbus_data", json_data)
                    json_data_dict = json.loads(json_data)
                    self.db_handler.save_json(json_data_dict)
                
            except Exception as e:
                print(f"Error publishing MQTT data: {e}")

            self.msleep(self.time_up)

    def read_int(self, client, address, count):
        try:
            regs = client.read_holding_registers(address, count)
            return regs[0] if regs else None
        except Exception as e:
            print(f"Error reading WORD at address {address}: {e}")
            return None

    def read_float(self, client, address):
        try:
            regs = client.read_holding_registers(address, 2)
            if regs:
                combined = struct.pack('<HH', regs[0], regs[1])
                return struct.unpack('<f', combined)[0]
            return None
        except Exception as e:
            print(f"Error reading FLOAT at address {address}: {e}")
            return None

    def stop_run(self):
        """Menghentikan thread dengan aman."""
        print("Stop requested...")
        self.run_worker = False
        self.is_stopping = True
        self.mqtt_thread.stop_pub()
        self.quit()
        self.wait(1000)
        if self.isRunning():
            print("Thread did not stop, forcing termination...")
            self.terminate()
            self.wait()
        self.db_handler.close()
        print("Thread stopped successfully.")

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(1049, 980)
        MainWindow.setStyleSheet("background-color: rgb(0, 0, 0);")
        self.centralwidget = QtWidgets.QWidget(MainWindow)
        self.centralwidget.setObjectName("centralwidget")
        MainWindow.setWindowFlags(MainWindow.windowFlags() & ~QtCore.Qt.WindowMaximizeButtonHint)

        #Global Var
        self.slave = None
        self.port_TCP = None
        self.unit_id_TCP = None
        self.broker_MQTT = None
        self.port_MQTT = None
        self.topic_MQTT = None
        self.host_Db = None
        self.user_Db = None
        self.name_Db = None
        self.name_Tb = None
        self.pass_Db = None
        self.time_update = None

        self.Header_Frame = QtWidgets.QFrame(self.centralwidget)
        self.Header_Frame.setGeometry(QtCore.QRect(20, 22, 1011, 111))
        self.Header_Frame.setStyleSheet("background-color: rgb(81, 81, 81);border: 1px solid gray; border-radius: 10px;")
        self.Header_Frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.Header_Frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.Header_Frame.setObjectName("Header_Frame")
        self.LOGO = QtWidgets.QLabel(self.Header_Frame)
        self.LOGO.setGeometry(QtCore.QRect(50, 5, 91, 101))
        self.LOGO.setText("")
        self.LOGO.setPixmap(QtGui.QPixmap("../../image-removebg-preview.png"))
        self.LOGO.setScaledContents(True)
        self.LOGO.setStyleSheet("border:None;")
        self.LOGO.setObjectName("LOGO")
        self.Nama_Label = QtWidgets.QLabel(self.Header_Frame)
        self.Nama_Label.setGeometry(QtCore.QRect(500, 40, 251, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(10)
        font.setBold(True)
        font.setWeight(75)
        self.Nama_Label.setFont(font)
        self.Nama_Label.setStyleSheet("color: rgb(255, 255, 255);border:None;")
        self.Nama_Label.setAlignment(QtCore.Qt.AlignCenter)
        self.Nama_Label.setObjectName("Nama_Label")
        self.Sidebar_Frame = QtWidgets.QFrame(self.centralwidget)
        self.Sidebar_Frame.setGeometry(QtCore.QRect(20, 145, 260, 800))
        self.Sidebar_Frame.setStyleSheet("background-color: rgb(81, 81, 81);border-radius:10px")
        self.Sidebar_Frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.Sidebar_Frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.Sidebar_Frame.setObjectName("Sidebar_Frame")
        self.MB_Setup_Frame = QtWidgets.QFrame(self.Sidebar_Frame)
        self.MB_Setup_Frame.setGeometry(QtCore.QRect(10, 10, 241, 171))
        self.MB_Setup_Frame.setStyleSheet("background-color: rgb(95, 95, 95);")
        self.MB_Setup_Frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.MB_Setup_Frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.MB_Setup_Frame.setObjectName("MB_Setup_Frame")
        self.MB_TCP_Label = QtWidgets.QLabel(self.MB_Setup_Frame)
        self.MB_TCP_Label.setGeometry(QtCore.QRect(40, 10, 161, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(10)
        font.setBold(True)
        font.setWeight(75)
        self.MB_TCP_Label.setFont(font)
        self.MB_TCP_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.MB_TCP_Label.setAlignment(QtCore.Qt.AlignCenter)
        self.MB_TCP_Label.setObjectName("MB_TCP_Label")
        self.IP_Label = QtWidgets.QLabel(self.MB_Setup_Frame)
        self.IP_Label.setGeometry(QtCore.QRect(20, 50, 21, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(8)
        font.setBold(True)
        font.setWeight(75)
        self.IP_Label.setFont(font)
        self.IP_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.IP_Label.setObjectName("IP_Label")
        self.Port_MB_Label = QtWidgets.QLabel(self.MB_Setup_Frame)
        self.Port_MB_Label.setGeometry(QtCore.QRect(20, 90, 41, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(8)
        font.setBold(True)
        font.setWeight(75)
        self.Port_MB_Label.setFont(font)
        self.Port_MB_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.Port_MB_Label.setObjectName("Port_MB_Label")
        self.Unit_ID_Label = QtWidgets.QLabel(self.MB_Setup_Frame)
        self.Unit_ID_Label.setGeometry(QtCore.QRect(20, 130, 51, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(8)
        font.setBold(True)
        font.setWeight(75)
        self.Unit_ID_Label.setFont(font)
        self.Unit_ID_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.Unit_ID_Label.setObjectName("Unit_ID_Label")
        self.IP_TextBox = QtWidgets.QTextEdit(self.MB_Setup_Frame)
        self.IP_TextBox.setGeometry(QtCore.QRect(102, 50, 104, 31))
        self.IP_TextBox.setStyleSheet("background-color: rgb(255, 255, 255);")
        self.IP_TextBox.setObjectName("IP_TextBox")
        self.Port_MB_TextBox = QtWidgets.QTextEdit(self.MB_Setup_Frame)
        self.Port_MB_TextBox.setGeometry(QtCore.QRect(102, 90, 104, 31))
        self.Port_MB_TextBox.setStyleSheet("background-color: rgb(255, 255, 255);")
        self.Port_MB_TextBox.setObjectName("Port_MB_TextBox")
        self.Unit_ID_TextBox = QtWidgets.QTextEdit(self.MB_Setup_Frame)
        self.Unit_ID_TextBox.setGeometry(QtCore.QRect(102, 130, 104, 31))
        self.Unit_ID_TextBox.setStyleSheet("background-color: rgb(255, 255, 255);")
        self.Unit_ID_TextBox.setObjectName("Unit_ID_TextBox")
        self.MQTT_Setup_Frame = QtWidgets.QFrame(self.Sidebar_Frame)
        self.MQTT_Setup_Frame.setGeometry(QtCore.QRect(10, 190, 241, 171))
        self.MQTT_Setup_Frame.setStyleSheet("background-color: rgb(95, 95, 95);")
        self.MQTT_Setup_Frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.MQTT_Setup_Frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.MQTT_Setup_Frame.setObjectName("MQTT_Setup_Frame")
        self.MQTT_Label = QtWidgets.QLabel(self.MQTT_Setup_Frame)
        self.MQTT_Label.setGeometry(QtCore.QRect(40, 10, 161, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(10)
        font.setBold(True)
        font.setWeight(75)
        self.MQTT_Label.setFont(font)
        self.MQTT_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.MQTT_Label.setAlignment(QtCore.Qt.AlignCenter)
        self.MQTT_Label.setObjectName("MQTT_Label")
        self.Broker_Label = QtWidgets.QLabel(self.MQTT_Setup_Frame)
        self.Broker_Label.setGeometry(QtCore.QRect(20, 50, 51, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(8)
        font.setBold(True)
        font.setWeight(75)
        self.Broker_Label.setFont(font)
        self.Broker_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.Broker_Label.setObjectName("Broker_Label")
        self.Port_MQTT_Label = QtWidgets.QLabel(self.MQTT_Setup_Frame)
        self.Port_MQTT_Label.setGeometry(QtCore.QRect(20, 90, 41, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(8)
        font.setBold(True)
        font.setWeight(75)
        self.Port_MQTT_Label.setFont(font)
        self.Port_MQTT_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.Port_MQTT_Label.setObjectName("Port_MQTT_Label")
        self.Topic_MQTT_Label = QtWidgets.QLabel(self.MQTT_Setup_Frame)
        self.Topic_MQTT_Label.setGeometry(QtCore.QRect(20, 130, 51, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(8)
        font.setBold(True)
        font.setWeight(75)
        self.Topic_MQTT_Label.setFont(font)
        self.Topic_MQTT_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.Topic_MQTT_Label.setObjectName("Topic_MQTT_Label")
        self.Port_MQTT_TextBox = QtWidgets.QTextEdit(self.MQTT_Setup_Frame)
        self.Port_MQTT_TextBox.setGeometry(QtCore.QRect(102, 90, 104, 31))
        self.Port_MQTT_TextBox.setStyleSheet("background-color: rgb(255, 255, 255);")
        self.Port_MQTT_TextBox.setObjectName("Port_MQTT_TextBox")
        self.Broker_TextBox = QtWidgets.QTextEdit(self.MQTT_Setup_Frame)
        self.Broker_TextBox.setGeometry(QtCore.QRect(102, 50, 104, 31))
        self.Broker_TextBox.setStyleSheet("background-color: rgb(255, 255, 255);")
        self.Broker_TextBox.setObjectName("Broker_TextBox")
        self.Topic_MQTT_TextBox = QtWidgets.QTextEdit(self.MQTT_Setup_Frame)
        self.Topic_MQTT_TextBox.setGeometry(QtCore.QRect(102, 130, 104, 31))
        self.Topic_MQTT_TextBox.setStyleSheet("background-color: rgb(255, 255, 255);")
        self.Topic_MQTT_TextBox.setObjectName("Topic_MQTT_TextBox")
        self.Database_Setup_Frame = QtWidgets.QFrame(self.Sidebar_Frame)
        self.Database_Setup_Frame.setGeometry(QtCore.QRect(10, 370, 241, 251))
        self.Database_Setup_Frame.setStyleSheet("background-color: rgb(95, 95, 95);")
        self.Database_Setup_Frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.Database_Setup_Frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.Database_Setup_Frame.setObjectName("Database_Setup_Frame")
        self.Database_Label = QtWidgets.QLabel(self.Database_Setup_Frame)
        self.Database_Label.setGeometry(QtCore.QRect(40, 10, 161, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(10)
        font.setBold(True)
        font.setWeight(75)
        self.Database_Label.setFont(font)
        self.Database_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.Database_Label.setAlignment(QtCore.Qt.AlignCenter)
        self.Database_Label.setObjectName("Database_Label")
        self.Host_Label = QtWidgets.QLabel(self.Database_Setup_Frame)
        self.Host_Label.setGeometry(QtCore.QRect(20, 50, 31, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(8)
        font.setBold(True)
        font.setWeight(75)
        self.Host_Label.setFont(font)
        self.Host_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.Host_Label.setObjectName("Host_Label")
        self.User_Label = QtWidgets.QLabel(self.Database_Setup_Frame)
        self.User_Label.setGeometry(QtCore.QRect(20, 90, 41, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(8)
        font.setBold(True)
        font.setWeight(75)
        self.User_Label.setFont(font)
        self.User_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.User_Label.setObjectName("User_Label")
        self.TB_Name_Label = QtWidgets.QLabel(self.Database_Setup_Frame)
        self.TB_Name_Label.setGeometry(QtCore.QRect(20, 170, 61, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(8)
        font.setBold(True)
        font.setWeight(75)
        self.TB_Name_Label.setFont(font)
        self.TB_Name_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.TB_Name_Label.setObjectName("TB_Name_Label")
        self.Password_Label = QtWidgets.QLabel(self.Database_Setup_Frame)
        self.Password_Label.setGeometry(QtCore.QRect(20, 210, 71, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(8)
        font.setBold(True)
        font.setWeight(75)
        self.Password_Label.setFont(font)
        self.Password_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.Password_Label.setObjectName("Password_Label")
        self.DB_Name_Label = QtWidgets.QLabel(self.Database_Setup_Frame)
        self.DB_Name_Label.setGeometry(QtCore.QRect(20, 130, 71, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(8)
        font.setBold(True)
        font.setWeight(75)
        self.DB_Name_Label.setFont(font)
        self.DB_Name_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.DB_Name_Label.setObjectName("DB_Name_Label")
        self.User_TextBox = QtWidgets.QTextEdit(self.Database_Setup_Frame)
        self.User_TextBox.setGeometry(QtCore.QRect(102, 90, 104, 31))
        self.User_TextBox.setStyleSheet("background-color: rgb(255, 255, 255);")
        self.User_TextBox.setObjectName("User_TextBox")
        self.Db_Name_TextBox = QtWidgets.QTextEdit(self.Database_Setup_Frame)
        self.Db_Name_TextBox.setGeometry(QtCore.QRect(102, 130, 104, 31))
        self.Db_Name_TextBox.setStyleSheet("background-color: rgb(255, 255, 255);")
        self.Db_Name_TextBox.setObjectName("Db_Name_TextBox")
        self.Host_TextBox = QtWidgets.QTextEdit(self.Database_Setup_Frame)
        self.Host_TextBox.setGeometry(QtCore.QRect(102, 50, 104, 31))
        self.Host_TextBox.setStyleSheet("background-color: rgb(255, 255, 255);")
        self.Host_TextBox.setObjectName("Host_TextBox")
        self.TB_Name_TextBox = QtWidgets.QTextEdit(self.Database_Setup_Frame)
        self.TB_Name_TextBox.setGeometry(QtCore.QRect(102, 170, 104, 31))
        self.TB_Name_TextBox.setStyleSheet("background-color: rgb(255, 255, 255);")
        self.TB_Name_TextBox.setObjectName("TB_Name_TextBox")
        self.Password_TextBox = QtWidgets.QTextEdit(self.Database_Setup_Frame)
        self.Password_TextBox.setGeometry(QtCore.QRect(102, 210, 104, 31))
        self.Password_TextBox.setStyleSheet("background-color: rgb(255, 255, 255);")
        self.Password_TextBox.setObjectName("Password_TextBox")
        self.Mode_Frame = QtWidgets.QFrame(self.Sidebar_Frame)
        self.Mode_Frame.setGeometry(QtCore.QRect(10, 630, 241, 151))
        self.Mode_Frame.setStyleSheet("background-color: rgb(95, 95, 95);")
        self.Mode_Frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.Mode_Frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.Mode_Frame.setObjectName("Mode_Frame")
        self.Time_Label = QtWidgets.QLabel(self.Mode_Frame)
        self.Time_Label.setGeometry(QtCore.QRect(52, 56, 41, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(8)
        font.setBold(True)
        font.setWeight(75)
        self.Time_Label.setFont(font)
        self.Time_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.Time_Label.setObjectName("Time_Label")
        self.PB_Update_Setup = QtWidgets.QPushButton(self.Mode_Frame)
        self.PB_Update_Setup.setGeometry(QtCore.QRect(55, 100, 141, 41))
        font = QtGui.QFont()
        font.setPointSize(9)
        font.setBold(True)
        font.setWeight(75)
        self.PB_Update_Setup.setFont(font)
        self.PB_Update_Setup.setStyleSheet("background-color: rgb(129, 129, 129);\n"
"color: rgb(255, 255, 255);")
        self.PB_Update_Setup.setObjectName("PB_Update_Setup")
        self.PB_Update_Setup.setCursor(QtCore.Qt.PointingHandCursor)

        self.ms_label = QtWidgets.QLabel(self.Mode_Frame)
        self.ms_label.setGeometry(QtCore.QRect(174, 58, 21, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(8)
        font.setBold(True)
        font.setWeight(75)
        self.ms_label.setFont(font)
        self.ms_label.setStyleSheet("color: rgb(255, 255, 255);")
        self.ms_label.setObjectName("ms_label")
        self.mqtt_update_checkBox = QtWidgets.QCheckBox(self.Mode_Frame)
        self.mqtt_update_checkBox.setGeometry(QtCore.QRect(55, 8, 131, 20))
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.mqtt_update_checkBox.setFont(font)
        self.mqtt_update_checkBox.setStyleSheet("color: rgb(255, 255, 255);")
        self.mqtt_update_checkBox.setObjectName("mqtt_update_checkBox")
        self.database_checkBox = QtWidgets.QCheckBox(self.Mode_Frame)
        self.database_checkBox.setGeometry(QtCore.QRect(55, 30, 141, 20))
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.database_checkBox.setFont(font)
        self.database_checkBox.setStyleSheet("color: rgb(255, 255, 255);")
        self.database_checkBox.setObjectName("database_checkBox")
        self.Time_TextBox = QtWidgets.QTextEdit(self.Mode_Frame)
        self.Time_TextBox.setGeometry(QtCore.QRect(90, 56, 81, 31))
        self.Time_TextBox.setStyleSheet("background-color: rgb(255, 255, 255);")
        self.Time_TextBox.setObjectName("Time_TextBox")

        self.INT_Table = QtWidgets.QTableWidget(self.centralwidget)
        self.INT_Table.setGeometry(QtCore.QRect(300, 218, 351, 611))
        self.INT_Table.setStyleSheet("background-color: rgb(81, 81, 81);color:white; gridline-color: rgb(0,0,0);")
        self.palette = self.INT_Table.palette()
        self.palette.setColor(QtGui.QPalette.Base, QtGui.QColor(81, 81, 81))  # Warna dasar tabel
        self.INT_Table.setPalette(self.palette)
        self.INT_Table.setObjectName("INT_Table")
        self.INT_Table.setColumnCount(3)
        self.INT_Table.setHorizontalHeaderLabels(["Register", "Name", "Value"])
        self.INT_Table.setAlternatingRowColors(False)  # Alternating row colors
        self.INT_Table.setShowGrid(True)  # Show grid lines
        self.INT_Table.horizontalHeader().setStretchLastSection(True)  # Stretch the last section
        # self.INT_Table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.INT_Table.verticalHeader().setVisible(False)  # Hide vertical header
        self.INT_Table.setWordWrap(True)  # Wrap text for cells
        self.header_INT = self.INT_Table.horizontalHeader()
        self.header_INT.setStyleSheet("QHeaderView::section { background-color: rgb(60, 60, 60); color: white; padding: 5px;}")
        self.INT_Table.setRowCount(0)
        table_width_INT = self.INT_Table.width()
        self.INT_Table.setColumnWidth(0, int(table_width_INT * 0.2))  # 20% untuk kolom "Reg"
        self.INT_Table.setColumnWidth(1, int(table_width_INT * 0.3))  # 40% untuk kolom "Variable"
        self.INT_Table.setColumnWidth(2, int(table_width_INT * 0.436))  # 40% untuk kolom "Value"


        self.FLOAT_Table = QtWidgets.QTableWidget(self.centralwidget)
        self.FLOAT_Table.setGeometry(QtCore.QRect(680, 218, 351, 611))
        self.FLOAT_Table.setStyleSheet("background-color: rgb(81, 81, 81); color:white; gridline-color: rgb(0,0,0);")
        self.FLOAT_Table.setObjectName("FLOAT_Table")
        self.FLOAT_Table.setColumnCount(3)
        self.FLOAT_Table.setHorizontalHeaderLabels(["Register", "Variable", "Value"])
        self.FLOAT_Table.setAlternatingRowColors(False)  # Alternating row colors
        self.FLOAT_Table.setShowGrid(True)  # Show grid lines
        self.FLOAT_Table.horizontalHeader().setStretchLastSection(True)  # Stretch the last section
        # self.INT_Table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.FLOAT_Table.verticalHeader().setVisible(False)  # Hide vertical header
        self.FLOAT_Table.setWordWrap(True)  # Wrap text for cells
        self.header_FLOAT = self.FLOAT_Table.horizontalHeader()
        self.header_FLOAT.setStyleSheet("QHeaderView::section { background-color: rgb(60, 60, 60); color: white; padding: 5px;}")
        self.FLOAT_Table.setRowCount(0)
        table_width_FLOAT = self.FLOAT_Table.width()
        self.FLOAT_Table.setColumnWidth(0, int(table_width_FLOAT * 0.2))  # 20% untuk kolom "Reg"
        self.FLOAT_Table.setColumnWidth(1, int(table_width_FLOAT * 0.3))  # 40% untuk kolom "Variable"
        self.FLOAT_Table.setColumnWidth(2, int(table_width_FLOAT * 0.436))  # 40% untuk kolom "Value"

        self.PB_Remove_Row_INT = QtWidgets.QPushButton(self.centralwidget)
        self.PB_Remove_Row_INT.setGeometry(QtCore.QRect(300, 842, 171, 41))
        font = QtGui.QFont()
        font.setPointSize(9)
        font.setBold(True)
        font.setWeight(75)
        self.PB_Remove_Row_INT.setFont(font)
        self.PB_Remove_Row_INT.setStyleSheet("background-color: rgb(129, 129, 129);color: rgb(255, 255, 255);border-radius:10px")
        self.PB_Remove_Row_INT.setObjectName("PB_Remove_Row_INT")
        self.PB_Add_Row_INT = QtWidgets.QPushButton(self.centralwidget)
        self.PB_Add_Row_INT.setGeometry(QtCore.QRect(480, 842, 171, 41))
        font = QtGui.QFont()
        font.setPointSize(9)
        font.setBold(True)
        font.setWeight(75)
        self.PB_Add_Row_INT.setFont(font)
        self.PB_Add_Row_INT.setStyleSheet("background-color: rgb(129, 129, 129);color: rgb(255, 255, 255); border-radius:10px")
        self.PB_Add_Row_INT.setObjectName("PB_Add_Row_INT")
        self.PB_Add_Row_INT.setCursor(QtCore.Qt.PointingHandCursor)

        self.PB_Add_Row_FLOAT = QtWidgets.QPushButton(self.centralwidget)
        self.PB_Add_Row_FLOAT.setGeometry(QtCore.QRect(860, 842, 171, 41))
        font = QtGui.QFont()
        font.setPointSize(9)
        font.setBold(True)
        font.setWeight(75)
        self.PB_Add_Row_FLOAT.setFont(font)
        self.PB_Add_Row_FLOAT.setStyleSheet("background-color: rgb(129, 129, 129);color: rgb(255, 255, 255);border-radius:10px")
        self.PB_Add_Row_FLOAT.setObjectName("PB_Add_Row_FLOAT")
        self.PB_Add_Row_FLOAT.setCursor(QtCore.Qt.PointingHandCursor)

        self.PB_Remove_Row_FLOAT = QtWidgets.QPushButton(self.centralwidget)
        self.PB_Remove_Row_FLOAT.setGeometry(QtCore.QRect(680, 842, 171, 41))
        font = QtGui.QFont()
        font.setPointSize(9)
        font.setBold(True)
        font.setWeight(75)
        self.PB_Remove_Row_FLOAT.setFont(font)
        self.PB_Remove_Row_FLOAT.setStyleSheet("background-color: rgb(129, 129, 129);color: rgb(255, 255, 255);border-radius:10px")
        self.PB_Remove_Row_FLOAT.setObjectName("PB_Remove_Row_FLOAT")
        self.PB_Run = QtWidgets.QPushButton(self.centralwidget)
        self.PB_Run.setGeometry(QtCore.QRect(300, 892, 351, 41))
        font = QtGui.QFont()
        font.setPointSize(9)
        font.setBold(True)
        font.setWeight(75)
        self.PB_Run.setFont(font)
        self.PB_Run.setStyleSheet("""
    QPushButton {
        background-color: rgb(102,204,0);
        color: rgb(255, 255, 255);
        border-radius: 10px;
    }
    QPushButton:disabled {
        background-color: rgb(200, 200, 200);  /* Warna pucat ketika disabled */
        color: rgb(150, 150, 150);  /* Warna teks yang lebih pucat */
    }
""")
        self.PB_Run.setObjectName("PB_Run")
        self.PB_Run.setCursor(QtCore.Qt.PointingHandCursor)

        self.PB_Stop = QtWidgets.QPushButton(self.centralwidget)
        self.PB_Stop.setGeometry(QtCore.QRect(680, 892, 351, 41))
        font = QtGui.QFont()
        font.setPointSize(9)
        font.setBold(True)
        font.setWeight(75)
        self.PB_Stop.setFont(font)
        self.PB_Stop.setStyleSheet("""
    QPushButton {
        background-color: red;
        color: rgb(255, 255, 255);
        border-radius: 10px;
    }
    QPushButton:disabled {
        background-color: rgb(200, 200, 200);  /* Warna pucat ketika disabled */
        color: rgb(150, 150, 150);  /* Warna teks yang lebih pucat */
    }
""")
        self.PB_Stop.setObjectName("PB_Stop")
        self.PB_Stop.setCursor(QtCore.Qt.PointingHandCursor)
        
        self.INT_Data_Frame = QtWidgets.QFrame(self.centralwidget)
        self.INT_Data_Frame.setGeometry(QtCore.QRect(300, 146, 351, 61))
        self.INT_Data_Frame.setStyleSheet("background-color: rgb(81, 81, 81);border-radius:10px")
        self.INT_Data_Frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.INT_Data_Frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.INT_Data_Frame.setObjectName("INT_Data_Frame")
        self.INT_Data_Label = QtWidgets.QLabel(self.INT_Data_Frame)
        self.INT_Data_Label.setGeometry(QtCore.QRect(90, 14, 161, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(10)
        font.setBold(True)
        font.setWeight(75)
        self.INT_Data_Label.setFont(font)
        self.INT_Data_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.INT_Data_Label.setAlignment(QtCore.Qt.AlignCenter)
        self.INT_Data_Label.setObjectName("INT_Data_Label")
        self.FLOAT_Data_Frame = QtWidgets.QFrame(self.centralwidget)
        self.FLOAT_Data_Frame.setGeometry(QtCore.QRect(680, 146, 351, 61))
        self.FLOAT_Data_Frame.setStyleSheet("background-color: rgb(81, 81, 81);border-radius:10px")
        self.FLOAT_Data_Frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.FLOAT_Data_Frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.FLOAT_Data_Frame.setObjectName("FLOAT_Data_Frame")
        self.FLOAT_Data_Label = QtWidgets.QLabel(self.FLOAT_Data_Frame)
        self.FLOAT_Data_Label.setGeometry(QtCore.QRect(100, 13, 161, 31))
        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei")
        font.setPointSize(10)
        font.setBold(True)
        font.setWeight(75)
        self.FLOAT_Data_Label.setFont(font)
        self.FLOAT_Data_Label.setStyleSheet("color: rgb(255, 255, 255);")
        self.FLOAT_Data_Label.setAlignment(QtCore.Qt.AlignCenter)
        self.FLOAT_Data_Label.setObjectName("FLOAT_Data_Label")
        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QtWidgets.QMenuBar(MainWindow)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 1049, 26))
        self.menubar.setObjectName("menubar")
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QtWidgets.QStatusBar(MainWindow)
        self.statusbar.setObjectName("statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.retranslateUi(MainWindow)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

        #Connect Button
        self.PB_Update_Setup.clicked.connect(self.get_text_values)
        self.PB_Add_Row_INT.clicked.connect(self.add_row_int)
        self.PB_Remove_Row_INT.clicked.connect(self.remove_row_int)
        self.PB_Add_Row_FLOAT.clicked.connect(self.add_row_float)
        self.PB_Remove_Row_FLOAT.clicked.connect(self.remove_row_float)
        self.PB_Run.clicked.connect(self.run_read)
        self.PB_Stop.clicked.connect(self.stop_read)

        #Call Thread
        self.mqtt_thread = MQTTThread(mqtt_client= None, topic_prefix= None, broker=None,port_mqtt=None)
        self.db_handler = DatabaseHandler(host='localhost', user='root', password=None, database=None, table_name=None)
        self.MB_Worker = ModbusTCP_Worker(modbus_client = None, tableWidget = None, tableWidget_2 = None, mqtt_thread = None, db_handler = None, time_up = None)
        self.PB_Stop.setEnabled(False)

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "MainWindow"))
        self.Nama_Label.setText(_translate("MainWindow", "NAMA PERUSAHAAN"))
        self.MB_TCP_Label.setText(_translate("MainWindow", "Modbus TCP Setup"))
        self.IP_Label.setText(_translate("MainWindow", "IP"))
        self.Port_MB_Label.setText(_translate("MainWindow", "Port"))
        self.Unit_ID_Label.setText(_translate("MainWindow", "Unit ID"))
        self.MQTT_Label.setText(_translate("MainWindow", "MQTT Setup"))
        self.Broker_Label.setText(_translate("MainWindow", "Broker"))
        self.Port_MQTT_Label.setText(_translate("MainWindow", "Port"))
        self.Topic_MQTT_Label.setText(_translate("MainWindow", "Topic"))
        self.Database_Label.setText(_translate("MainWindow", "Database Setup"))
        self.Host_Label.setText(_translate("MainWindow", "Host"))
        self.User_Label.setText(_translate("MainWindow", "User"))
        self.TB_Name_Label.setText(_translate("MainWindow", "TB Name"))
        self.Password_Label.setText(_translate("MainWindow", "Password"))
        self.DB_Name_Label.setText(_translate("MainWindow", "DB Name"))
        self.Time_Label.setText(_translate("MainWindow", "Time"))
        self.PB_Update_Setup.setText(_translate("MainWindow", "Update Setup"))
        self.ms_label.setText(_translate("MainWindow", "ms"))
        self.mqtt_update_checkBox.setText(_translate("MainWindow", "MQTT Update"))
        self.database_checkBox.setText(_translate("MainWindow", "Database Update"))
        self.PB_Remove_Row_INT.setText(_translate("MainWindow", "Remove Row"))
        self.PB_Add_Row_INT.setText(_translate("MainWindow", "Add Row"))
        self.PB_Add_Row_FLOAT.setText(_translate("MainWindow", "Add Row"))
        self.PB_Remove_Row_FLOAT.setText(_translate("MainWindow", "Remove Row"))
        self.PB_Run.setText(_translate("MainWindow", "RUN"))
        self.PB_Stop.setText(_translate("MainWindow", "STOP"))
        self.INT_Data_Label.setText(_translate("MainWindow", "INT Data"))
        self.FLOAT_Data_Label.setText(_translate("MainWindow", "FLOAT Data"))
        
    def initialize_modbus_client(self):
        global modbus_client
        modbus_client = ModbusClient(host=self.slave, port=self.port_TCP, unit_id=self.unit_id_TCP, auto_open=True)
        self.MB_Worker = ModbusTCP_Worker(modbus_client, self.INT_Table, self.FLOAT_Table, self.mqtt_thread, self.db_handler, self.time_loop) 
        self.mqtt_thread = MQTTThread(self.mqtt_client, self.topic_MQTT, self.broker_MQTT, self.port_MQTT)
        self.db_handler = DatabaseHandler(self.host_Db, self.user_Db, self.pass_Db, self.name_Db,self.name_Tb)

        
    def get_text_values(self):
        try:
            slave_ip = self.IP_TextBox.toPlainText()
            port = int(self.Port_MB_TextBox.toPlainText())
            unit_id = int(self.Unit_ID_TextBox.toPlainText())
            broker = self.Broker_TextBox.toPlainText()
            port_mqtt = int(self.Port_MQTT_TextBox.toPlainText())
            topic = self.Topic_MQTT_TextBox.toPlainText()
            host = self.Host_TextBox.toPlainText()
            user = self.User_TextBox.toPlainText()
            db_name = self.Db_Name_TextBox.toPlainText()
            tb_name = self.TB_Name_TextBox.toPlainText()
            password = self.Password_TextBox.toPlainText()
            time_update = int(self.Time_TextBox.toPlainText())

            self.slave = slave_ip
            self.port_TCP = port
            self.unit_id_TCP = unit_id
            self.broker_MQTT = broker
            self.port_MQTT = port_mqtt
            self.topic_MQTT = topic
            self.host_Db = host
            self.user_Db = user
            self.name_Db = db_name
            self.name_Tb = tb_name
            self.pass_Db = password
            self.time_loop = time_update
            self.mqtt_client = mqtt.Client()
            self.mqtt_client.connect(self.broker_MQTT, self.port_MQTT, 60)
            self.initialize_modbus_client()

            print(f"slave_ip: {slave_ip}, type: {type(slave_ip)}")
            print(f"port: {port}, type: {type(port)}")
            print(f"unit_id: {unit_id}, type: {type(unit_id)}")
            print(f"broker: {broker}, type: {type(broker)}")
            print(f"mqtt_port: {port_mqtt}, type: {type(port_mqtt)}")
            print(f"topic: {topic}, type: {type(topic)}")
            print(f"host: {host}, type: {type(host)}")
            print(f"user: {user}, type: {type(user)}")
            print(f"db_name: {db_name}, type: {type(db_name)}")
            print(f"tb_name: {tb_name}, type: {type(tb_name)}")
            print(f"password: {password}, type: {type(password)}")
            print(f'slave: {self.slave}, port_TCP: {self.port_TCP}, unit_id_TCP: {self.unit_id_TCP}')
        except ValueError as e:
            print(f"Error converting input: {e}")

    def add_row_int(self):
        # Tambahkan baris ke tabel INT
        row_position = self.INT_Table.rowCount()
        self.INT_Table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)  # Perbaiki scrolling
        self.INT_Table.insertRow(row_position)
        
        # Membuat item baru untuk kolom 0
        item_0 = QTableWidgetItem()
        item_0.setTextAlignment(QtCore.Qt.AlignCenter)  # Mengatur teks agar rata tengah
    
        # Membuat item baru untuk kolom 1 dan 2
        item_1 = QTableWidgetItem()  # Ganti dengan nilai yang sesuai
        item_1.setTextAlignment(QtCore.Qt.AlignCenter)
        item_2 = QTableWidgetItem()  # Ganti dengan nilai yang sesuai
        item_2.setTextAlignment(QtCore.Qt.AlignCenter)
        # Menambahkan item ke kolom-kolom yang sesuai
        self.INT_Table.setItem(row_position, 0, item_0)
        self.INT_Table.setItem(row_position, 1, item_1)
        self.INT_Table.setItem(row_position, 2, item_2)

    def remove_row_int(self):
        current_row = self.INT_Table.currentRow()
        if current_row >= 0:
            self.INT_Table.removeRow(current_row)

    def add_row_float(self):
        row_position = self.FLOAT_Table.rowCount()
        self.FLOAT_Table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)  # Perbaiki scrolling
        self.FLOAT_Table.insertRow(row_position)
        
        # Membuat item baru untuk kolom 0
        item_0 = QTableWidgetItem()
        item_0.setTextAlignment(QtCore.Qt.AlignCenter)  # Mengatur teks agar rata tengah
    
        # Membuat item baru untuk kolom 1 dan 2
        item_1 = QTableWidgetItem()  # Ganti dengan nilai yang sesuai
        item_1.setTextAlignment(QtCore.Qt.AlignCenter)
        item_2 = QTableWidgetItem()  # Ganti dengan nilai yang sesuai
        item_2.setTextAlignment(QtCore.Qt.AlignCenter)
        # Menambahkan item ke kolom-kolom yang sesuai
        self.FLOAT_Table.setItem(row_position, 0, item_0)
        self.FLOAT_Table.setItem(row_position, 1, item_1)
        self.FLOAT_Table.setItem(row_position, 2, item_2)

    def remove_row_float(self):
        current_row = self.FLOAT_Table.currentRow()
        if current_row >= 0:
            self.FLOAT_Table.removeRow(current_row)

    def run_read(self):
        self.initialize_modbus_client()
        if not self.MB_Worker.isRunning():
            self.MB_Worker.int_update.connect(self.int_handle_update)
            self.MB_Worker.float_update.connect(self.float_handle_update)
            self.MB_Worker.run_worker = True  # Set flag untuk menjalankan loop
            self.MB_Worker.start()  # Mulai thread
            self.PB_Run.setEnabled(False)
            self.PB_Stop.setEnabled(True)
            print("Started Modbus reading thread.")
        
    def stop_read(self):
        self.MB_Worker.stop_run()  # Hentikan thread dengan aman
        self.PB_Run.setEnabled(True)
        self.PB_Stop.setEnabled(False)
        print("Stopped Modbus reading thread.")
        

    def int_handle_update(self, row, col, value):
        try:
            # Validasi baris dan kolom
            if row < self.INT_Table.rowCount() and col < self.INT_Table.columnCount():
                self.INT_Table.setItem(row, col, QTableWidgetItem(str(value)))
                print(f"Updated row {row}, col {col} with value: {value}")
            else:
                print(f"Invalid row ({row}) or column ({col}) index.")
        except Exception as e:
            print(f"Error updating table: {e}")

    def float_handle_update(self, row, col, value):
        try:
            # Validasi baris dan kolom
            if row < self.FLOAT_Table.rowCount() and col < self.FLOAT_Table.columnCount():
                self.FLOAT_Table.setItem(row, col, QTableWidgetItem(str(value)))
                print(f"Updated row {row}, col {col} with value: {value}")
            else:
                print(f"Invalid row ({row}) or column ({col}) index.")
        except Exception as e:
            print(f"Error updating table: {e}")


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    MainWindow = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(MainWindow)
    MainWindow.show()
    sys.exit(app.exec_())
