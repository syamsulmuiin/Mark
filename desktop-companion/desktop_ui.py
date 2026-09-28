"""MARK LV HUD layout around the MARK LIV companion transport and actions."""
from __future__ import annotations
import psutil
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QMainWindow, QMessageBox,
                             QPushButton, QTabWidget, QVBoxLayout, QWidget, QDialog)
from hud import C, HudCanvas, LogWidget, MetricBar


class Dispatcher(QObject):
    call = pyqtSignal(object, int)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.call.connect(lambda fn, delay: QTimer.singleShot(delay, fn))


class TextValue:
    def __init__(self, widget): self.widget = widget
    def get(self): return self.widget.text()
    def set(self, value): self.widget.setText(value)


class DesktopWindow(QMainWindow):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.dispatcher = Dispatcher(self)
        self.setWindowTitle('MARK LIV · Desktop Companion')
        self.resize(1040, 720)
        self.setMinimumSize(820, 580)
        self.setStyleSheet(f'''QWidget {{ background: {C.BG}; color: {C.TEXT}; font-family: 'Segoe UI', sans-serif; }}
            QFrame#panel {{ background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 5px; }}
            QLabel#title {{ color: {C.PRI}; font-size: 20px; font-weight: bold; }}
            QLabel#caption {{ color: {C.TEXT_DIM}; font-size: 11px; }}
            QLineEdit, QListWidget {{ background: {C.PANEL2}; color: {C.WHITE}; border: 1px solid {C.BORDER_B}; padding: 7px; border-radius: 3px; }}
            QPushButton {{ color: {C.PRI}; background: {C.PANEL2}; border: 1px solid {C.BORDER_B}; padding: 8px 10px; border-radius: 4px; }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
            QTabWidget::pane {{ border: 1px solid {C.BORDER}; }}
            QTabBar::tab {{ background: {C.PANEL}; color: {C.TEXT_MED}; padding: 9px 18px; }}
            QTabBar::tab:selected {{ color: {C.PRI}; border-bottom: 2px solid {C.PRI}; }}''')
        central = QWidget(); self.setCentralWidget(central)
        main = QVBoxLayout(central); main.setContentsMargins(16, 15, 16, 14); main.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel('MARK  /  LIV'); title.setObjectName('title'); header.addWidget(title)
        header.addStretch()
        self.status_label = QLabel('DISCONNECTED'); self.status_label.setStyleSheet(f'color: {C.ACC}; font-weight: bold;')
        header.addWidget(self.status_label)
        main.addLayout(header)
        row = QHBoxLayout(); row.setSpacing(12); main.addLayout(row, 1)
        left = self._panel(row, 158)
        self._label(left, 'DEVICE LINK')
        self.code_input = QLineEdit(); self.code_input.setPlaceholderText('Pair code'); left.addWidget(self.code_input)
        self.pair_button=self._button(left, 'PAIR DEVICE', owner.pair)
        self._button(left, 'CONNECT VOICE', owner.connect)
        self._button(left, 'DISCONNECT', owner.disconnect)
        left.addSpacing(16)
        self._label(left, 'LOCAL FILES')
        self._button(left, 'ATTACHMENTS', owner.show_attachments)
        left.addStretch()
        self._label(left, 'VOICE AND ACTIONS\nRUN ON THIS DEVICE')
        center = self._panel(row, 350, 1)
        self.hud = HudCanvas(assistant_name='J.A.R.V.I.S')
        center.addWidget(self.hud, 1)
        right = self._panel(row, 270)
        self._label(right, 'SYSTEM TELEMETRY')
        self.cpu = MetricBar('CPU'); self.mem = MetricBar('MEMORY'); self.disk = MetricBar('DISK')
        for bar in (self.cpu, self.mem, self.disk): right.addWidget(bar)
        self._label(right, 'COMPANION ACTIVITY')
        self.log = LogWidget(); right.addWidget(self.log, 1)
        self._label(right, 'COMMAND')
        cmdrow = QHBoxLayout(); right.addLayout(cmdrow)
        self.command_input = QLineEdit(); self.command_input.setPlaceholderText('Type a command')
        self.command_input.returnPressed.connect(owner.send); cmdrow.addWidget(self.command_input, 1)
        send = QPushButton('SEND'); send.clicked.connect(owner.send); cmdrow.addWidget(send)
        self.metrics_timer = QTimer(self); self.metrics_timer.timeout.connect(self.update_metrics); self.metrics_timer.start(3500)
        self.update_metrics()
    def _panel(self, row, width, stretch=0):
        panel = QFrame(); panel.setObjectName('panel'); panel.setMinimumWidth(width)
        layout = QVBoxLayout(panel); layout.setContentsMargins(12, 14, 12, 14); layout.setSpacing(9)
        row.addWidget(panel, stretch)
        return layout
    def _label(self, layout, value):
        label=QLabel(value); label.setObjectName('caption'); label.setWordWrap(True); layout.addWidget(label)
    def _button(self, layout, label, callback):
        btn=QPushButton(label); btn.clicked.connect(callback); layout.addWidget(btn)
        return btn
    def after(self, delay, callback): self.dispatcher.call.emit(callback, delay)
    def update_metrics(self):
        for bar, value in ((self.cpu, psutil.cpu_percent()), (self.mem, psutil.virtual_memory().percent), (self.disk, psutil.disk_usage(str(__import__('pathlib').Path.home())).percent)):
            bar.set_value(value, f'{value:.0f}%')
    def set_status(self, value):
        self.status_label.setText(value.upper())
        self.hud.state = value.upper()
        self.hud.speaking = value.upper() == 'SPEAKING'
    def closeEvent(self, event):
        self.owner.disconnect()
        super().closeEvent(event)


class AttachmentDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner.root)
        self.owner=owner
        self.setWindowTitle('Attachments · MARK LIV'); self.resize(600, 430)
        layout=QVBoxLayout(self)
        heading=QLabel('ATTACHMENTS'); heading.setObjectName('title'); layout.addWidget(heading)
        self.tabs=QTabWidget(); self.tabs.addTab(QWidget(), 'Received'); self.tabs.addTab(QWidget(), 'Sent')
        self.tabs.currentChanged.connect(lambda index: owner._show_attachment_mode('received' if index==0 else 'sent'))
        layout.addWidget(self.tabs)
        self.hint=QLabel('Received files can be opened or saved on this device.'); layout.addWidget(self.hint)
        self.items=QListWidget(); layout.addWidget(self.items, 1)
        row=QHBoxLayout(); layout.addLayout(row)
        self.actions=[]
        for label, action in (('OPEN','open'), ('SAVE AS','save'), ('SHARE','share')):
            btn=QPushButton(label); btn.clicked.connect(lambda _, a=action: owner.request_attachment(a)); row.addWidget(btn); self.actions.append(btn)
        row.addStretch()
        refresh=QPushButton('REFRESH'); refresh.clicked.connect(lambda: owner.ws and owner.ws.send(__import__('json').dumps({'type':'attachment.list'})))
        row.addWidget(refresh)
    def set_mode(self, mode):
        self.hint.setText('Sent history · Only the recipient can open or save these files.' if mode=='sent' else 'Received files can be opened or saved on this device.')
        for btn in self.actions: btn.setVisible(mode=='received')
