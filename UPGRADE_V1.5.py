"""
晟华光电升级工具 Release Notes:

Version 1.5 (2024-03-16):
- 新增功能：无
- 修复问题：修复了打包后exe文件图标显示不正确的问题。
- 改进：无

Important Notes:
- 请注意，在每次选择文件后，请确保文件路径保存成功，以避免下次点击文件按键时显示错误路径。
- 如果遇到任何问题或有建议，请及时联系我们进行反馈。
"""

import logging
import base64
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import serial
import serial.tools.list_ports

from ymodem import YMODEM

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

SCRIPT_VERSION = "1.5"
send_data_mutex = threading.Lock()


class SerialFlasherApp:
    def __init__(self, root):
        self.log = logging.getLogger('YReporter')
        self.root = root
        self.root.title("JS_V1.2.1")
        # img = b'AAABAAEAEBAAAAEAGADNAgAAFgAAAIlQTkcNChoKAAAADUlIRFIAAAAQAAAAEAgGAAAAH/P/YQAAAAFzUkdCAK7OHOkAAAAEZ0FNQQAAsY8L/GEFAAAACXBIWXMAAA7DAAAOwwHHb6hkAAACYklEQVQ4T21TaW+bQBT0//8jUeKbOE77oVFP9VCaKk0VBzAG4jQxtsGYYwEDO53FapUmkRjt2+Xt7Oy8ty1ZL2VdSymklHW1hyyJ3R5/1x4jY36u8jm2ZFXj1Ahx4BYYmxnGRo5jQ0BrkOFEF0SKUTNyfpNDswr0pzE+2g9olQA6jkDfDjGyEhybCYb/kDbzYyZrUzWqeYreLGG+wMCK0MpI0LYzLkZM2CLgPJZAWgMFcWgXOLM9XK7Q/Hu1okp9w3ySkaiVNwr2BCMy+vEGk/lvXDtzxKXEa2OJmuMnx0dV1vi5DTC+XaFvkcBO/yfo6h5+2A6urFskXBfc0HMTRIzfT71GUcr4ygvRUQqeEmiGh7WUCGhsymskoAJnhTDb4S4sUWQ5PFHg65omKr8eE3StLc7DAvcihai5m998s8abmc/TFhjbLi6XG1YgQMeI0FOmPlNwE2FgrnG5CTBkCd+aHtq3yvUIH4IU7645Z0Xas6IhemZi17SAHatAjKcPkFWOswntV3L4VRVDGjGkfG3Kqj1VoIc5FqKi6zUeeF/BeEzz2HzkrRByhBQ4mG1x5G5fuIIT4/wuwMUiQMkfo/kCR/chIp665PFWnLNHJIZ6go79goKOHqOUNU4mLFYm4fox+m6I734JPWbrWi59mWMTVE0XNgSCBD12YpcEI9PHKXuhbZX4cp/iG0/XDB89M8JwFuKC9f/MtS6Nbs/4ZpSJJW+nqd6mMUOWUvX5gAb1GB+6NNaiCpIP+A4GSqWdMCdm24c4nQZoKXd/LWJK4mYnb9B1CmIfv4SOyxy+Gy+I8AfsD6ZHYDR/UwAAAABJRU5ErkJggg=='
        # tmp = open("tmp.ico", "wb+")
        # tmp.write(base64.b64decode(img))  # 写入到临时文件中
        # tmp.close()
        # root.iconbitmap("tmp.ico")  # 设置图标
        # os.remove("tmp.ico")

        self.ser = [serial.Serial(bytesize=8,
                                  stopbits=1,
                                  timeout=1,
                                  xonxoff=False,
                                  rtscts=False,
                                  parity="N") for _ in range(1)]
        self.queue = queue.Queue()
        self.open_all_button_enabled = True
        self.close_all_button_enabled = False
        self.lock = threading.Lock()
        self.ymodem_sender = YMODEM(lambda size: self.sender_getc(size, row), lambda data: self.sender_putc(data, row))

        # 文件选择部分
        self.file_path = [tk.StringVar() for _ in range(1, 9)]  # 修改这里，为每个interface行创建一个file_path变量

        # 串口部分
        self.serial_rows = []
        self.progress_bars = []
        self.progress_percentage = []
        self.available_ports = []  # 存储所有可用串口
        self.rows = []  # 存储串口行
        self.opened_ports = []  # 用于记录已打开的串口列表
        self.opened_ports_count = 0  # 记录成功打开的串口数量

        self.upgrade_commands = ["$SH,UPGRADE,MAIN", "$SH,UPGRADE,IMU", "$SH,UPGRADE,M1", "$SH,UPGRADE,M2",
                                 "$SH,UPGRADE,M3", "$SH,UPGRADE,MP", "$JS,UPGRADE,MOTOR", "$JS,UPGRADE,IMU"]

        self.interface_names = ["MAIN", "IMU", "M1", "M2", "M3", "MP", "MOTOR", "JS_IMU"]

        # 类变量用于存储可用串口列表
        SerialFlasherApp.available_ports = []

        # 创建1个串口行的GUI控件
        for i in range(1):
            serial_row = self.create_serial_row()
            serial_row['port_status'] = 'Closed'
            self.serial_rows.append(serial_row)

        # 创建8个接口行的GUI控件，并传递接口名称
        for i, interface_name in enumerate(self.interface_names):
            upgrade_row = self.create_upgrade_row(i + 1, interface_name)
            self.rows.append(upgrade_row)

        # 定时检测可用串口
        self.update_ports_thread = threading.Thread(target=self.update_ports_loop, daemon=True)
        self.update_ports_thread.start()

        # 在初始化时禁用所有串口行的'关闭串口'按键
        for row in range(len(self.serial_rows)):
            self.serial_rows[0]['close_button']['state'] = tk.DISABLED

    # 创建1个串口行的各个控件
    def create_serial_row(self):
        frame = tk.Frame(self.root)

        # 每个串口行选定的串口
        port_var = tk.StringVar()

        # 每个串口行的串口显示框
        port_label = tk.Label(frame, text=f"串口:", width=10, height=3, relief=tk.SUNKEN, font=("宋体", 12))
        port_label.grid(row=0, column=0, sticky=tk.E, padx=5, pady=0)

        # 每个串口行的串口下拉框显示的串口
        port_combobox = ttk.Combobox(frame, textvariable=port_var, state="readonly", width=20, )
        port_combobox.grid(row=0, column=1, padx=5, pady=0)

        # 创建一个波特率的 Combobox 控件
        baudrate_var = tk.StringVar()
        baudrate_combobox = ttk.Combobox(frame, textvariable=baudrate_var, state="readonly", width=20)
        baudrate_combobox['values'] = ["300", "600", "1200", "2400", "4800", "9600", "19200", "38400",
                                       "57600", "115200", "128000", "230400", "256000", "460800", "921600"]
        baudrate_combobox.grid(row=0, column=2, padx=5, pady=0)

        # 每个串口行的打开串口按键
        open_button = tk.Button(frame, text="打开串口", command=lambda: self.open_serial(0, port_var), width=10, height=3,
                                font=("宋体", 12))
        open_button.grid(row=0, column=3, padx=5, pady=0)

        # 每个串口行的关闭串口按键
        close_button = tk.Button(frame, text="关闭串口", command=lambda: self.close_serial(0, port_var),
                                 state=tk.DISABLED, width=10, height=3, font=("宋体", 12))
        close_button.grid(row=0, column=4, padx=5, pady=0)

        frame.grid(row=1, column=0, columnspan=3, pady=0, sticky='ew')

        return {
            'port_combobox': port_combobox,
            'baudrate_combobox': baudrate_combobox,  # 添加波特率的 Combobox
            'open_button': open_button,
            'close_button': close_button,
        }

    # 创建8个接口行的各个控件
    def create_upgrade_row(self, row, interface_name):
        frame = tk.Frame(self.root)

        # 每个接口行的接口显示框
        upgrade_label = tk.Label(frame, text=f"{interface_name}", width=8, height=2, relief=tk.SUNKEN, )
        upgrade_label.grid(row=0, column=0, sticky=tk.E, padx=5, pady=0)

        # 每个接口行的选择升级文件按键
        select_file_button = tk.Button(frame, text="选择接口{}升级文件".format(row), height=2,
                                       command=lambda row=row: self.select_file(row))  # 为每个升级接口行的选择文件按钮添加一个row参数
        select_file_button.grid(row=0, column=1, padx=5, pady=5)

        # 每个接口行的文件显示Entry
        file_path_entry = tk.Entry(frame, textvariable=self.file_path[row - 1], width=30,
                                   font=('宋体', 13))  # 使用对应interface行的file_path变量
        file_path_entry.grid(row=0, column=2, padx=5, pady=0)

        # 每个接口行的烧录按键
        flash_button = tk.Button(frame, text="升级",
                                 command=lambda row=row: self.flash(row, self.serial_rows[0]['port_combobox'].get()),
                                 state=tk.DISABLED, height=2, width=8, font=('宋体', 12))  # 修改这里，将选定的串口传递给flash函数
        flash_button.grid(row=0, column=3, padx=5, pady=0)

        # 烧录进度条控件
        progress_bar = ttk.Progressbar(frame, orient=tk.HORIZONTAL, length=200, mode='determinate')
        progress_bar.grid(row=0, column=4, padx=5, pady=0)

        # 烧录进度条百分比
        percentage_label = tk.Label(frame, text="0%")
        percentage_label.grid(row=0, column=5, padx=5, pady=0)

        # 烧录状态显示框
        flash_status_label = tk.Label(frame, fg='grey', text="准备升级", height=2, relief=tk.RIDGE, font=('宋体', 12))
        flash_status_label.grid(row=0, column=6, padx=5, pady=0)

        frame.grid(row=row + 2, column=0, columnspan=3, pady=0, sticky='ew')

        return {
            'select_file_button': select_file_button,
            'file_path_entry': file_path_entry,
            'flash_button': flash_button,
            'progress_bar': progress_bar,
            'percentage_label': percentage_label,
            'flash_status_label': flash_status_label,
        }

    # 选择文件函数
    def select_file(self, row):  # 修改这里，为select_file函数添加一个row参数
        filename = filedialog.askopenfilename()
        if filename:
            self.file_path[row - 1].set(filename)  # 更新对应interface行的file_path变量
            self.rows[row - 1]['flash_button']['state'] = tk.NORMAL  # 文件选择后，将对应行的烧录按钮状态设置为正常

    # 获取当前可用的串口列表
    def get_available_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        all_available_ports = sorted(ports)
        return all_available_ports

    def sender_getc(self, size, row):
        # print('getc: ', self.ser[0].read(size))
        print('row-sender', row)
        return self.ser[0].read(size) or None

    def sender_putc(self, data, row):
        send_data_mutex.acquire()
        self.ser[0].write(data)
        send_data_mutex.release()

    # 打开串口
    def open_serial(self, row, port_var):
        selected_port = port_var.get()
        selected_baudrate = self.serial_rows[0]['baudrate_combobox'].get()  # 获取所选的波特率
        if selected_port:
            try:
                self.ser[0].port = selected_port
                self.ser[0].baudrate = int(selected_baudrate)  # 设置波特率
                if not self.ser[0].is_open:
                    self.ser[0].open()
                    print('baud rate:', self.serial_rows[0]['baudrate_combobox'].get())
                    # 更新串口状态
                    self.open_serial_status()
                    # 记录已打开的串口信息
                    port_info = {'name': selected_port, 'baudrate': selected_baudrate}
                    self.opened_ports.append(port_info)
                    self.opened_ports_count += 1
            except serial.SerialException as e:
                print(e)
                messagebox.showinfo("提示", f"串口 {selected_port} 打开失败！")
        elif not selected_port:
            messagebox.showinfo("提示", "请先选择串口！")

    # 关闭串口
    # 在 close_serial 方法中获取所选的波特率并关闭串口
    def close_serial(self, row, port_var):
        selected_port = port_var.get()
        if not self.ser[0].isOpen():
            messagebox.showinfo("提示", "串口未连接！")
            self.close_serial_status()  # 串口未连接，则关闭串口按键状态恢复到打开串口前的状态
        else:
            try:
                self.ser[0].close()
                print('baud rate:', self.serial_rows[0]['baudrate_combobox'].get())
                # 更新串口状态
                self.close_serial_status()
                self.opened_ports_count -= 1
                # 从已打开的串口列表中移除已关闭的串口
                self.opened_ports = [port for port in self.opened_ports if port['name'] != selected_port]
            except serial.SerialException as e:
                print(e)
                messagebox.showinfo(title="提示", message='串口关闭失败！')
                self.close_serial_status()  # 串口关闭失败，则关闭串口按键状态恢复到打开串口前的状态
                return

    # 根据串口打开成功更新各个控件的状态
    def open_serial_status(self):
        self.serial_rows[0]['open_button']['state'] = tk.DISABLED  # 串口打开成功后，打开串口按键置灰
        self.serial_rows[0]['close_button']['state'] = tk.NORMAL  # 串口打开成功后，关闭串口按键高亮

    # 根据串口关闭成功更新各个控件的状态
    def close_serial_status(self):
        self.serial_rows[0]['close_button']['state'] = tk.DISABLED  # 串口关闭成功后，关闭串口按键置灰
        self.serial_rows[0]['open_button']['state'] = tk.NORMAL  # 串口关闭成功后，打开串口按键高亮

    # 每2秒定时检查一次可用串口
    def update_ports_loop(self):
        while True:
            available_ports = self.get_available_ports()

            # 将所有可用串口显示在串口下拉框中
            if available_ports:
                sorted_ports = sorted(list(available_ports))
                self.serial_rows[0]['port_combobox']['values'] = sorted_ports
                # 如果用户没有选择一个串口，那么将第一个可用串口设置为默认显示的串口
                if not self.serial_rows[0]['port_combobox'].get():
                    self.serial_rows[0]['port_combobox'].set(sorted_ports[0])
            else:
                self.serial_rows[0]['port_combobox']['values'] = []
                self.serial_rows[0]['port_combobox'].set('')

            time.sleep(2)

    # 串口烧录逻辑及其方法
    def burn_in_thread(self, row, port_var, upgrade_command):
        # 在这里重新初始化ymodem_sender
        self.ymodem_sender = YMODEM(lambda size: self.sender_getc(size, row), lambda data: self.sender_putc(data, row))
        #   烧录过程中禁用烧录按键,关闭串口按键和选择文件按键,烧录状态显示框显示‘烧录中’
        self.serial_rows[0]['close_button']['state'] = tk.DISABLED
        self.rows[row]['flash_button']['state'] = tk.DISABLED
        self.rows[row]['select_file_button']['state'] = tk.DISABLED
        self.rows[row]['flash_status_label'].configure(fg='blue', text="升级中...")

        self.log.info(f"*** interface{row + 1}The burning thread starts！")
        self.ser[0].port = port_var
        if self.ser[0].isOpen():
            self.log.info(f"<<< 串口已打开！")
        elif not self.ser[0].isOpen():
            self.log.info(f"<<< 串口未打开！")
            messagebox.showinfo("提示", "串口未打开！")
            self.rows[row]['flash_status_label'].configure(fg='grey', text="准备升级")
            self.rows[row]['flash_button']['state'] = tk.NORMAL
            self.rows[row]['select_file_button']['state'] = tk.NORMAL
            return

        file = self.file_path[row].get()
        print("<<< The burning file is:", file)
        print("<<< Open file：", file)
        retry_count = 0

        if len(file) <= 0:
            messagebox.showinfo("提示", "请选择正确的文件！")
            return
        else:
            self.ser[0].write((upgrade_command + "\r\n").encode('UTF-8'))
            print(">>> interface{} send upgrade instructions :'{}'！".format(row + 1, upgrade_command))
            time.sleep(2)
            print('Waiting for 2s after sending upgrade instructions!\r\n')
            while True:
                response = self.ser[0].read(4)
                print("<<< interface{}  received are:{}\r\n".format(row + 1, response))
                if b'C' in response:
                    print("<<< interface{}  received 'CCCC'！\r\n".format(row + 1))
                    break
                else:
                    print("<<< interface{}  received are:{}\r\n".format(row + 1, response))
                    # self.ser[0].write((upgrade_command + "\r\n").encode('UTF-8'))
                    # print(">>> interface{} send upgrade instructions :'{}'！".format(row + 1, upgrade_command))
                    retry_count += 1
                if retry_count > 10:
                    self.log.info(f"*** interface{row + 1} flash failed！")
                    #   判断烧录是否结束，如果 flash failed，就更新按键状态：打开烧录按键,关闭串口按键和选择文件按键
                    self.serial_rows[0]['close_button']['state'] = tk.NORMAL
                    self.rows[row]['flash_button']['state'] = tk.NORMAL
                    self.rows[row]['flash_status_label'].configure(fg='red', text="升级失败！")
                    self.rows[row]['select_file_button']['state'] = tk.NORMAL
                    return False

            # 在调用 ymodem_send 方法之前，确保 self.progress_bars 列表的长度至少为 row + 1
            while len(self.progress_bars) < row + 1:
                progress_bar = ttk.Progressbar(self.root, orient=tk.HORIZONTAL, length=200, mode='determinate')
                self.progress_bars.append(progress_bar)

            self.progress_bars[row].configure(value=0)
            self.ymodem_send(file, row, lambda percentage: self.progress_bars[row].configure(value=percentage))

    #   通过ymodem协议发送升级文件
    def ymodem_send(self, file_path, row, progress_callback):
        try:
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)
        except FileNotFoundError:
            self.log.info("<<< 烧录文件未找到!")
            return

        with open(file_path, 'rb') as file_stream:
            def callback(percentage):
                if percentage < 100 or percentage == 100:
                    self.root.after(0, progress_callback, percentage)
                    self.root.after(0, self.update_percentage_label, row, percentage)
                    self.root.after(0, self.update_progress_bar_label, row, percentage)
                    self.log.info(f"<<<sent_percentage: {percentage}")
                elif percentage > 100:
                    percentage = 100
                    self.root.after(0, progress_callback, percentage)
                    self.root.after(0, self.update_percentage_label, row, percentage)
                    self.root.after(0, self.update_progress_bar_label, row, percentage)
                    self.log.info(f"<<<sent_percentage: {percentage}")

            #   烧录状态标志位返回及判断
            def flash_status_callback(flash_status):
                #   flash_status为1表示烧录成功
                if flash_status == 1:
                    self.log.info(f"*** 第{row + 1}行串口烧录完成！")
                    #   判断烧录是否结束，如果烧录完成，就更新按键状态：打开烧录按键,关闭串口按键和选择文件按键
                    self.serial_rows[0]['close_button']['state'] = tk.NORMAL
                    self.rows[row]['flash_button']['state'] = tk.NORMAL
                    self.rows[row]['flash_status_label'].configure(fg='green', text="升级成功！")
                    self.rows[row]['select_file_button']['state'] = tk.NORMAL
                #   flash_status为2表示 flash failed
                elif flash_status == 2:
                    self.log.info(f"*** serial port on line{row + 1} flash failed！")
                    #   判断烧录是否结束，如果 flash failed，就更新按键状态：打开烧录按键,关闭串口按键和选择文件按键
                    self.serial_rows[0]['close_button']['state'] = tk.NORMAL
                    self.rows[row]['flash_button']['state'] = tk.NORMAL
                    self.rows[row]['flash_status_label'].configure(fg='red', text="升级失败！")
                    self.rows[row]['select_file_button']['state'] = tk.NORMAL

            self.ymodem_sender.send(file_stream, file_name, file_size, callback=callback,
                                    flash_status_callback=flash_status_callback)

    #   更新烧录百分比变化
    def update_percentage_label(self, row, percentage):
        self.rows[row]['percentage_label'].configure(text=f"{percentage}%")

    #   更新烧录进度条变化
    def update_progress_bar_label(self, row, percentage):
        self.rows[row]['progress_bar'].configure(value=percentage)

    #   烧录按键
    def flash(self, row, port_var):
        # 烧录逻辑
        # 启动一个线程执行烧录
        file_path = self.file_path[row - 1].get()
        if file_path and port_var:  # 检查是否已选择文件
            self.ser[0].port = port_var
            threading.Thread(target=self.burn_in_thread, args=(row - 1, port_var, self.upgrade_commands[row - 1]),
                             daemon=True).start()
        else:
            messagebox.showinfo("提示", "请先打开串口！")


if __name__ == "__main__":
    root = tk.Tk()
    # root.geometry("800x800")  # 设置窗口大小
    # root.grid_propagate(False)  # 防止窗口大小自动调整
    app = SerialFlasherApp(root)
    root.mainloop()
    print('Script Version:', SCRIPT_VERSION)

