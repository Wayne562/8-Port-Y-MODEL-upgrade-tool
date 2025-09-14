# -*- coding: utf-8 -*-
"""
UPGRADE_V1.5.1
在原有版本基础上新增 UDP 行与配置/连接功能：
1) 串口行下面新增 UDP 行（UDP 标签 → 配置 → Server IP 显示 → 连接 → 关闭）
2) “配置”弹窗：local ip / local port / server ip / server port
3) UDP 连接成功：串口“打开/关闭”按钮置灰；失败：串口行恢复默认
4) UDP 连接成功后，下面升级仍旧是 YMODEM，sender_getc/putc 自动走 UDP
5) 调整UI布局，窗口最大化后，控件也随之调整
"""

import logging
import base64
import os
import queue
import threading
import time
import socket
import ipaddress
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import serial
import serial.tools.list_ports

from ymodem import YMODEM

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

SCRIPT_VERSION = "1.5.1"
send_data_mutex = threading.Lock()


class SerialFlasherApp:
    def __init__(self, root):
        self.log = logging.getLogger('YReporter')
        self.root = root
        self.root.title("UPGRADE_V1.5.1")

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
        # 让根窗口第0列可拉伸（根上所有子 Frame 都在 column=0）
        self.root.grid_columnconfigure(0, weight=1)

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

        # ✅ UDP 状态与配置
        self.udp_connected = False
        self.udp_sock = None
        self.udp_rx_buf = bytearray()
        self.udp_conf = {
            "local_ip": "",
            "local_port": "",
            "server_ip": "",
            "server_port": "",
        }
        self.udp_server_ip_var = tk.StringVar(value="")  # UDP 行里显示用

        # ✅ 创建 UDP 行（位于串口行下面）
        self.udp_row = self.create_udp_row()

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

        # ✅ 让第1、2列（两个下拉）可横向拉伸
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(2, weight=1)

        # 每个串口行选定的串口
        port_var = tk.StringVar()

        # 每个串口行的串口显示框
        port_label = tk.Label(frame, text=f"串口", width=10, height=3, relief=tk.SUNKEN, font=("宋体", 12))
        port_label.grid(row=0, column=0, sticky=tk.E, padx=5, pady=0)

        # 每个串口行的串口下拉框显示的串口
        port_combobox = ttk.Combobox(frame, textvariable=port_var, state="readonly", width=20)
        port_combobox.grid(row=0, column=1, padx=5, pady=0, sticky='ew')

        # 创建一个波特率的 Combobox 控件
        baudrate_var = tk.StringVar()
        baudrate_combobox = ttk.Combobox(frame, textvariable=baudrate_var, state="readonly", width=25)
        baudrate_combobox['values'] = ["300", "600", "1200", "2400", "4800", "9600", "19200", "38400",
                                       "57600", "115200", "128000", "230400", "256000", "460800", "921600"]
        baudrate_combobox.grid(row=0, column=2, padx=5, pady=0, sticky='ew')

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

        # ✅ 让第2列（文件路径）与第4列（进度条）可横向拉伸
        frame.grid_columnconfigure(2, weight=2)
        frame.grid_columnconfigure(4, weight=1)

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
        file_path_entry.grid(row=0, column=2, padx=5, pady=0, sticky='ew')  # 文件显示 Entry（✅ 加 sticky）

        # 每个接口行的烧录按键
        flash_button = tk.Button(frame, text="升级",
                                 command=lambda row=row: self.flash(row, self.serial_rows[0]['port_combobox'].get()),
                                 state=tk.DISABLED, height=2, width=8, font=('宋体', 12))  # 修改这里，将选定的串口传递给flash函数
        flash_button.grid(row=0, column=3, padx=5, pady=0)

        # 烧录进度条控件
        progress_bar = ttk.Progressbar(frame, orient=tk.HORIZONTAL, length=200, mode='determinate')
        progress_bar.grid(row=0, column=4, padx=5, pady=0, sticky='ew')  # 进度条（✅ 加 sticky；length=200 只是初始宽度）

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

    def create_udp_row(self):
        """
        UDP 行，从左到右：
        [UDP] [配置] [Server IP Entry] [连接] [关闭]
        """
        frame = tk.Frame(self.root)

        # ✅ 让第2列（Server IP 输入框）可横向拉伸
        frame.grid_columnconfigure(2, weight=1)

        # label
        udp_label = tk.Label(frame, text="UDP", width=10, height=3, relief=tk.SUNKEN, font=("宋体", 12))
        udp_label.grid(row=0, column=0, sticky=tk.E, padx=5, pady=0)

        # 配置按钮
        cfg_btn = tk.Button(frame, text="UDP配置", width=10, height=3, font=("宋体", 12),
                            command=self.udp_config_dialog)
        cfg_btn.grid(row=0, column=1, padx=5, pady=0)

        # Server IP 显示（只读）
        server_ip_entry = tk.Entry(frame, textvariable=self.udp_server_ip_var, width=30, font=('宋体', 13),
                                   state="readonly")
        server_ip_entry.grid(row=0, column=2, padx=5, pady=0, sticky='ew')

        # 连接按钮
        connect_btn = tk.Button(frame, text="连接", width=10, height=3, font=("宋体", 12),
                                command=self.udp_connect)
        connect_btn.grid(row=0, column=3, padx=5, pady=0)

        # 关闭按钮
        close_btn = tk.Button(frame, text="关闭", width=10, height=3, font=("宋体", 12),
                              state=tk.DISABLED, command=self.udp_close)
        close_btn.grid(row=0, column=4, padx=5, pady=0)

        # 布局在串口行下面（串口行是 row=1）
        frame.grid(row=2, column=0, columnspan=3, pady=0, sticky='ew')

        return {
            "frame": frame,
            "label": udp_label,
            "cfg_button": cfg_btn,
            "server_ip_entry": server_ip_entry,
            "connect_button": connect_btn,
            "close_button": close_btn,
        }

    def _guess_local_ip(self) -> str:
        """尽力猜一个本机 IP 作为默认值（失败就留空）"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            try:
                return socket.gethostbyname(socket.gethostname())
            except Exception:
                return ""

    def udp_config_dialog(self):
        import ipaddress
        top = tk.Toplevel(self.root)
        top.title("UDP 配置")
        top.grab_set()  # 模态

        # 旧值/默认值
        lv_ip = self.udp_conf.get("local_ip") or self._guess_local_ip()
        lv_port = self.udp_conf.get("local_port") or ""
        sv_ip = self.udp_conf.get("server_ip") or ""
        sv_port = self.udp_conf.get("server_port") or ""

        v_local_ip = tk.StringVar(value=lv_ip)
        v_local_port = tk.StringVar(value=lv_port)
        v_server_ip = tk.StringVar(value=sv_ip)
        v_server_port = tk.StringVar(value=sv_port)

        # ---- UI ----
        tk.Label(top, text="Local IP:").grid(row=0, column=0, sticky="e", padx=8, pady=6)
        e_local_ip = tk.Entry(top, textvariable=v_local_ip, width=24)
        e_local_ip.grid(row=0, column=1, padx=8, pady=6)

        tk.Label(top, text="Local Port:").grid(row=1, column=0, sticky="e", padx=8, pady=6)
        e_local_port = tk.Entry(top, textvariable=v_local_port, width=24)
        e_local_port.grid(row=1, column=1, padx=8, pady=6)

        tk.Label(top, text="Server IP:").grid(row=2, column=0, sticky="e", padx=8, pady=6)
        e_server_ip = tk.Entry(top, textvariable=v_server_ip, width=24)
        e_server_ip.grid(row=2, column=1, padx=8, pady=6)

        tk.Label(top, text="Server Port:").grid(row=3, column=0, sticky="e", padx=8, pady=6)
        e_server_port = tk.Entry(top, textvariable=v_server_port, width=24)
        e_server_port.grid(row=3, column=1, padx=8, pady=6)

        # ---- 小工具：高亮错误框 ----
        def _mark_ok(widget, ok: bool):
            try:
                widget.configure(bg=("#FFFFFF" if ok else "#FFECEC"))
            except Exception:
                pass

        # ---- 确定：逐项校验 + 保存 ----
        def on_ok():
            errs = []
            first_bad = None

            # 预设默认值，避免“可能未赋值”告警
            lpt = 0
            spt = 0

            # Local IP（可留空）
            lip = v_local_ip.get().strip()
            if lip:
                try:
                    ipaddress.ip_address(lip)
                    _mark_ok(e_local_ip, True)
                except ValueError:
                    errs.append("Local IP 格式无效，例如：192.168.1.100")
                    _mark_ok(e_local_ip, False)
                    first_bad = first_bad or e_local_ip
            else:
                _mark_ok(e_local_ip, True)

            # Local Port（可留空或 0）
            lpt_raw = v_local_port.get().strip()
            if lpt_raw == "":
                lpt = 0
                _mark_ok(e_local_port, True)
            else:
                if lpt_raw.isdigit():
                    lpt = int(lpt_raw)
                    if not (0 <= lpt <= 65535):
                        errs.append("Local Port 超出范围（应为 0~65535）")
                        _mark_ok(e_local_port, False)
                        first_bad = first_bad or e_local_port
                    else:
                        _mark_ok(e_local_port, True)
                else:
                    errs.append("Local Port 必须是整数（0~65535）")
                    _mark_ok(e_local_port, False)
                    first_bad = first_bad or e_local_port

            # Server IP（必填）
            sip = v_server_ip.get().strip()
            try:
                ipaddress.ip_address(sip)
                _mark_ok(e_server_ip, True)
            except ValueError:
                errs.append("Server IP 不能为空且必须是合法 IP（例如：192.168.1.200）")
                _mark_ok(e_server_ip, False)
                first_bad = first_bad or e_server_ip

            # Server Port（必填 1~65535）
            spt_raw = v_server_port.get().strip()
            if spt_raw.isdigit():
                spt = int(spt_raw)
                if not (1 <= spt <= 65535):
                    errs.append("Server Port 超出范围（应为 1~65535）")
                    _mark_ok(e_server_port, False)
                    first_bad = first_bad or e_server_port
                else:
                    _mark_ok(e_server_port, True)
            else:
                errs.append("Server Port 必须是整数（1~65535）")
                _mark_ok(e_server_port, False)
                first_bad = first_bad or e_server_port

            if errs:
                messagebox.showinfo("配置有误", "请检查以下项目：\n\n" + "\n".join(f"• {m}" for m in errs))
                if first_bad:
                    first_bad.focus_set()
                return

            # 保存配置 & 刷新主界面显示（显示 ip:port 或只 ip）
            self.udp_conf.update({
                "local_ip": lip,
                "local_port": str(lpt),
                "server_ip": sip,
                "server_port": str(spt),
            })
            # 如果你有 _update_udp_target_display() 就用它；没有就直接设置：
            try:
                self._update_udp_target_display()
            except Exception:
                self.udp_server_ip_var.set(f"{sip}:{spt}" if sip and spt else sip)

            top.destroy()

        # ---- 清除配置：清空四项并同步清空主界面显示 ----
        def on_clear():
            # 清空弹窗里的输入框
            v_local_ip.set("")
            v_local_port.set("")
            v_server_ip.set("")
            v_server_port.set("")
            _mark_ok(e_local_ip, True)
            _mark_ok(e_local_port, True)
            _mark_ok(e_server_ip, True)
            _mark_ok(e_server_port, True)

            # 清空全局配置
            self.udp_conf.update({
                "local_ip": "",
                "local_port": "",
                "server_ip": "",
                "server_port": "",
            })
            # 清空主界面显示
            self.udp_server_ip_var.set("")  # 若你实现了 _update_udp_target_display() 也可以调用它

            # 关闭弹窗（如需保留弹窗让用户继续编辑，可注释掉这一行）
            top.destroy()

        # 按钮区：确定 / 清除配置
        btn_ok = tk.Button(top, text="确定", width=10, command=on_ok)
        btn_ok.grid(row=4, column=0, padx=8, pady=10)

        btn_clear = tk.Button(top, text="清除配置", width=10, command=on_clear)
        btn_clear.grid(row=4, column=1, padx=8, pady=10)

    def _format_udp_target(self, ip: str, port: str) -> str:
        ip = (ip or "").strip()
        port = (port or "").strip()
        if not ip and not port:
            return ""
        # IPv6 用 [ip]:port 的形式展示
        if ":" in ip and not (ip.startswith("[") and ip.endswith("]")):
            ip = f"[{ip}]"
        return f"{ip}:{port}" if port else ip

    def _update_udp_target_display(self):
        sip = self.udp_conf.get("server_ip") or ""
        spt = self.udp_conf.get("server_port") or ""
        self.udp_server_ip_var.set(self._format_udp_target(sip, spt))

    def udp_connect(self):
        # 校验配置
        conf = self.udp_conf
        try:
            lip = conf.get("local_ip") or ""
            lpt = int(conf.get("local_port") or "0")
            sip = conf.get("server_ip") or ""
            spt = int(conf.get("server_port") or "0")
            if not (sip and spt):
                messagebox.showinfo("提示", "请先配置 Server IP/Port")
                return
            if lip:
                ipaddress.ip_address(lip)
            ipaddress.ip_address(sip)
            if not (0 <= lpt <= 65535 and 0 <= spt <= 65535):
                raise ValueError("端口范围应为 0~65535")
        except Exception as e:
            messagebox.showinfo("提示", f"配置非法：{e}")
            return

        # 建立/绑定/连接
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1.0)
            if lpt or lip:
                sock.bind((lip, lpt))
            # "连接"一个 UDP 目标，便于后续 recv() 只收该对端数据
            sock.connect((sip, spt))
            self._update_udp_target_display()
            self.udp_sock = sock
            self.udp_connected = True
            self.udp_rx_buf.clear()

            # ✅ UI：UDP 连接成功 → 禁用串口开/关按钮；UDP 连接按钮置灰，关闭按钮高亮
            self.ui_call(self.serial_rows[0]['open_button'].configure, state=tk.DISABLED)
            self.ui_call(self.serial_rows[0]['close_button'].configure, state=tk.DISABLED)
            self.ui_call(self.udp_row['connect_button'].configure, state=tk.DISABLED)
            self.ui_call(self.udp_row['close_button'].configure, state=tk.NORMAL)

            messagebox.showinfo("提示", f"UDP 已连接到 {sip}:{spt}")

        except Exception as e:
            self.udp_connected = False
            self.udp_sock = None
            self.udp_rx_buf.clear()
            # ✅ UI：连接失败 → 恢复串口行默认状态（打开=可点、关闭=置灰；UDP 连接按钮可点，关闭置灰）
            self.ui_call(self.serial_rows[0]['open_button'].configure, state=tk.NORMAL)
            self.ui_call(self.serial_rows[0]['close_button'].configure, state=tk.DISABLED)
            self.ui_call(self.udp_row['connect_button'].configure, state=tk.NORMAL)
            self.ui_call(self.udp_row['close_button'].configure, state=tk.DISABLED)
            messagebox.showinfo("提示", f"UDP 连接失败：{e}")

    def udp_close(self):
        try:
            if self.udp_sock:
                self.udp_sock.close()
        finally:
            self.udp_sock = None
            self.udp_connected = False
            self.udp_rx_buf.clear()
            # ✅ UI：关闭 UDP → 串口按钮恢复默认；UDP 连接按钮可点，关闭置灰
            self.ui_call(self.serial_rows[0]['open_button'].configure, state=tk.NORMAL)
            self.ui_call(self.serial_rows[0]['close_button'].configure, state=tk.DISABLED)
            self.ui_call(self.udp_row['connect_button'].configure, state=tk.NORMAL)
            self.ui_call(self.udp_row['close_button'].configure, state=tk.DISABLED)

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
        # ✅ 如果 UDP 已连接，优先走 UDP
        if self.udp_connected and self.udp_sock:
            try:
                # 用一个缓冲把 datagram 拆成字节流，满足 YMODEM 对 getc(1) 的调用习惯
                if not self.udp_rx_buf:
                    pkt = self.udp_sock.recv(4096)  # 单次尽量多收一点
                    if pkt:
                        self.udp_rx_buf.extend(pkt)
                if not self.udp_rx_buf:
                    return None
                # 按请求大小返回
                out = bytes(self.udp_rx_buf[:size])
                del self.udp_rx_buf[:size]
                return out or None
            except socket.timeout:
                return None
            except Exception:
                return None

        # 串口路径（原有逻辑）
        return self.ser[0].read(size) or None

    def sender_putc(self, data, row):
        # ✅ UDP 已连接则走 UDP
        if self.udp_connected and self.udp_sock:
            try:
                self.udp_sock.send(data)
            except Exception:
                pass
            return

        # 串口路径（原有逻辑）
        send_data_mutex.acquire()
        try:
            self.ser[0].write(data)
        finally:
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
        if not self.ser[0].is_open:
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
        self.ui_call(self.serial_rows[0]['open_button'].configure, state=tk.DISABLED)  # 串口打开成功后，打开串口按键置灰
        self.ui_call(self.serial_rows[0]['close_button'].configure, state=tk.NORMAL)  # 串口打开成功后，关闭串口按键高亮

    # 根据串口关闭成功更新各个控件的状态
    def close_serial_status(self):
        self.ui_call(self.serial_rows[0]['close_button'].configure, state=tk.DISABLED)  # 串口关闭成功后，关闭串口按键置灰
        self.ui_call(self.serial_rows[0]['open_button'].configure, state=tk.NORMAL)  # 串口关闭成功后，打开串口按键高亮

    # 每2秒定时检查一次可用串口
    def update_ports_loop(self):
        """后台线程：轮询串口；UI 更新丢回主线程执行"""
        while True:
            try:
                available = self.get_available_ports()
                ports = sorted(list(available)) if available else []
                # 关键：把 UI 更新切回主线程，避免跨线程操作 Tk 控件
                self.root.after(0, self._apply_ports_to_combo, ports)
            except Exception:
                logging.exception("ports poll error")
            time.sleep(2)

    def _apply_ports_to_combo(self, ports):
        """在主线程里安全地更新下拉框"""
        combo = self.serial_rows[0]['port_combobox']
        if ports:
            # 仅在列表变化时更新，减少闪动
            if tuple(combo['values']) != tuple(ports):
                combo['values'] = ports
            current = combo.get()
            if not current or current not in ports:
                combo.set(ports[0])
        else:
            combo['values'] = []
            combo.set('')

    def ui_call(self, fn, *args, **kwargs):
        """在 Tk 主线程中执行 fn(*args, **kwargs)（修复跨线程更新 UI 的问题）"""
        self.root.after(0, lambda: fn(*args, **kwargs))

    # 串口烧录逻辑及其方法
    def burn_in_thread(self, row, port_var, upgrade_command):
        # 在这里重新初始化ymodem_sender
        self.ymodem_sender = YMODEM(lambda size: self.sender_getc(size, row), lambda data: self.sender_putc(data, row))
        #   烧录过程中禁用烧录按键,关闭串口按键和选择文件按键,烧录状态显示框显示‘烧录中’
        self.ui_call(self.serial_rows[0]['close_button'].configure, state=tk.DISABLED)
        self.ui_call(self.rows[row]['flash_button'].configure, state=tk.DISABLED)
        self.ui_call(self.rows[row]['select_file_button'].configure, state=tk.DISABLED)
        self.ui_call(self.rows[row]['flash_status_label'].configure, fg='blue', text="升级中.")

        self.log.info(f"*** interface{row + 1}The burning thread starts！")
        self.ser[0].port = port_var
        if self.ser[0].is_open:
            self.log.info(f"<<< 串口已打开！")
        elif not self.ser[0].is_open:
            self.log.info(f"<<< 串口未打开！")
            self.ui_call(messagebox.showinfo, "提示", "串口未打开！")
            self.ui_call(self.rows[row]['flash_status_label'].configure, fg='grey', text="准备升级")
            self.ui_call(self.rows[row]['flash_button'].configure, state=tk.NORMAL)
            self.ui_call(self.rows[row]['select_file_button'].configure, state=tk.NORMAL)
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
                    self.ui_call(self.serial_rows[0]['close_button'].configure, state=tk.NORMAL)
                    self.ui_call(self.rows[row]['flash_button'].configure, state=tk.NORMAL)
                    self.ui_call(self.rows[row]['flash_status_label'].configure, fg='red', text="升级失败！")
                    self.ui_call(self.rows[row]['select_file_button'].configure, state=tk.NORMAL)
                    return False

            # 在调用 ymodem_send 方法之前，确保 self.progress_bars 列表的长度至少为 row + 1
            while len(self.progress_bars) < row + 1:
                progress_bar = ttk.Progressbar(self.root, orient=tk.HORIZONTAL, length=200, mode='determinate')
                self.progress_bars.append(progress_bar)

            self.root.after(0, self.progress_bars[row].configure, value=0)
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
                    self.ui_call(self.serial_rows[0]['close_button'].configure, state=tk.NORMAL)
                    self.ui_call(self.rows[row]['flash_button'].configure, state=tk.NORMAL)
                    self.ui_call(self.rows[row]['flash_status_label'].configure, fg='green', text="升级成功！")
                    self.ui_call(self.rows[row]['select_file_button'].configure, state=tk.NORMAL)
                #   flash_status为2表示 flash failed
                elif flash_status == 2:
                    self.log.info(f"*** serial port on line{row + 1} flash failed！")
                    #   判断烧录是否结束，如果 flash failed，就更新按键状态：打开烧录按键,关闭串口按键和选择文件按键
                    self.ui_call(self.serial_rows[0]['close_button'].configure, state=tk.NORMAL)
                    self.ui_call(self.rows[row]['flash_button'].configure, state=tk.NORMAL)
                    self.ui_call(self.rows[row]['flash_status_label'].configure, fg='red', text="升级失败！")
                    self.ui_call(self.rows[row]['select_file_button'].configure, state=tk.NORMAL)

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

