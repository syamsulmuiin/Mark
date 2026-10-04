"""Desktop Companion HUD layout around the Mark transport and local actions."""
from __future__ import annotations
import psutil
from PyQt6.QtCore import QObject, QRectF, Qt, QTimer, QUrl, QPoint, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QRadialGradient, QKeySequence, QFont
from PyQt6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QMainWindow, QMessageBox,
                             QPushButton, QStackedWidget, QTabWidget, QVBoxLayout, QWidget, QDialog,
                             QMenu, QSizePolicy, QSplitter, QTextEdit)
try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PyQt6.QtMultimediaWidgets import QVideoWidget
except Exception:
    QAudioOutput = QMediaPlayer = QVideoWidget = None
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


class GatewayMark(QWidget):
    """A small code-rendered reactor mark for the pairing surface."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(112,112)
    def paintEvent(self, _):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c=56.0
        glow=QRadialGradient(c,c,52)
        glow.setColorAt(0,QColor(0,212,255,45))
        glow.setColorAt(1,QColor(0,212,255,0))
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QBrush(glow));p.drawEllipse(QRectF(4,4,104,104))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for radius,alpha in ((43,55),(32,100),(23,165)):
            p.setPen(QPen(QColor(0,212,255,alpha),1.5))
            p.drawEllipse(QRectF(c-radius,c-radius,radius*2,radius*2))
        center=QRadialGradient(50,49,17)
        center.setColorAt(0,QColor('#67e5f4'))
        center.setColorAt(1,QColor('#007a99'))
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QBrush(center));p.drawEllipse(QRectF(43,43,26,26));p.end()

class DesktopWindow(QMainWindow):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.video_window = None
        self.video_player = None
        self.video_audio = None
        self.video_audio_player = None
        self.video_audio_output = None
        self.dispatcher = Dispatcher(self)
        self.setWindowTitle('Mark · Desktop Companion')
        self.resize(1040, 720)
        self.setMinimumSize(820, 580)
        self.setStyleSheet(f'''QWidget {{ color: {C.TEXT}; font-family: 'Segoe UI', sans-serif; }}
            QMainWindow, QStackedWidget, QWidget#loginPage, QWidget#dashboardPage {{ background: {C.BG}; }}
            QFrame#panel {{ background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 5px; }}
            QLabel#title {{ color: {C.PRI}; font-size: 20px; font-weight: bold; }}
            QLabel#caption {{ color: {C.TEXT_DIM}; font-size: 11px; }}
            QLineEdit, QListWidget {{ background: {C.PANEL2}; color: {C.WHITE}; border: 1px solid {C.BORDER_B}; padding: 7px; border-radius: 3px; }}
            QPushButton {{ color: {C.PRI}; background: {C.PANEL2}; border: 1px solid {C.BORDER_B}; padding: 8px 10px; border-radius: 4px; }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
            QTabWidget::pane {{ border: 1px solid {C.BORDER}; }}
            QTabBar::tab {{ background: {C.PANEL}; color: {C.TEXT_MED}; padding: 9px 18px; }}
            QTabBar::tab:selected {{ color: {C.PRI}; border-bottom: 2px solid {C.PRI}; }}''')
        self.setStyleSheet(self.styleSheet()+f"""
            QFrame#gatewayCard {{ background: #0c1116; border: 1px solid #273239; border-radius: 22px; }}
            QLabel#gatewayTitle {{ color: #f7f8f8; font-size: 24px; font-weight: bold; }}
            QLabel#gatewayHint {{ color: #9aabb1; font-size: 13px; }}
            QLabel#gatewayStatus {{ color: #9bb0b5; font-size: 12px; }}
            QLabel#gatewayBrand {{ color: #f7f8f8; font-size: 17px; font-weight: bold; letter-spacing: 4px; }}
            QLineEdit#gatewayInput {{ background: #10191d; border: 1px solid #315861; border-radius: 10px; color: #f7f8f8; font-size: 18px; padding: 10px; }}
            QLineEdit#gatewayInput:focus {{ border: 2px solid {C.PRI}; }}
            QPushButton#gatewayPrimary {{ color: #001417; background: #16d9f5; border: none; border-radius: 10px; font-size: 13px; font-weight: bold; padding: 12px; }}
            QPushButton#gatewayPrimary:disabled {{ color: #84999d; background: #193239; }}
            QPushButton#gatewaySecondary {{ border: none; color: #9ad9e0; background: transparent; }}
        """)
        self.pages=QStackedWidget(self);self.setCentralWidget(self.pages)
        self.login_page=self._make_login(owner)
        self.dashboard_page=QWidget(self);self.dashboard_page.setObjectName('dashboardPage')
        self.pages.addWidget(self.login_page);self.pages.addWidget(self.dashboard_page)
        self.pages.setCurrentWidget(self.login_page)
        central=self.dashboard_page
        root=QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        header=QWidget(); header.setFixedHeight(54); header.setStyleSheet(f'background:{C.DARK}; border-bottom:1px solid {C.BORDER_B};')
        h=QHBoxLayout(header); h.setContentsMargins(16,0,16,0); h.setSpacing(6)
        version=QLabel('COMPANION'); version.setFont(QFont('Courier New',8)); version.setStyleSheet(f'color:{C.PRI_DIM}; background:transparent;'); h.addWidget(version)
        self.setup_button=QPushButton('⚙'); self.setup_button.setFixedSize(28,28); self.setup_button.setToolTip('Settings and controls'); h.addWidget(self.setup_button)
        setup_menu=QMenu(self); setup_menu.addAction('Reconnect',owner.connect); setup_menu.addAction('Disconnect',owner.disconnect); setup_menu.addAction('Use a new Pair Code',owner.prepare_new_pair_code); setup_menu.addAction('Audio devices…',owner.choose_audio_devices); self.setup_button.setMenu(setup_menu)
        self.controls_button=QPushButton('🎛'); self.controls_button.setFixedSize(28,28); self.controls_button.setToolTip('Everyday controls'); h.addWidget(self.controls_button)
        controls_menu=QMenu(self); controls_menu.addAction('Interrupt response',owner.interrupt); controls_menu.addAction('Attachments…',owner.show_attachments); full=controls_menu.addAction('Full screen'); full.triggered.connect(self.toggle_fullscreen); self.controls_button.setMenu(controls_menu)
        h.addStretch()
        mid=QVBoxLayout(); mid.setSpacing(1)
        title=QLabel('J.A.R.V.I.S'); title.setAlignment(Qt.AlignmentFlag.AlignCenter); title.setFont(QFont('Courier New',17,QFont.Weight.Bold)); title.setStyleSheet(f'color:{C.PRI}; background:transparent;'); mid.addWidget(title)
        subtitle=QLabel('A Friendly Assistant'); subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter); subtitle.setFont(QFont('Courier New',7)); subtitle.setStyleSheet(f'color:{C.PRI_DIM}; background:transparent;'); mid.addWidget(subtitle); h.addLayout(mid)
        h.addStretch()
        clock_col=QVBoxLayout(); clock_col.setSpacing(2)
        self.status_label=QLabel('DISCONNECTED'); self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight); self.status_label.setFont(QFont('Courier New',7,QFont.Weight.Bold)); self.status_label.setStyleSheet(f'color:{C.ACC}; background:transparent;'); clock_col.addWidget(self.status_label)
        self.clock_label=QLabel('00:00:00'); self.clock_label.setAlignment(Qt.AlignmentFlag.AlignRight); self.clock_label.setFont(QFont('Courier New',14,QFont.Weight.Bold)); self.clock_label.setStyleSheet(f'color:{C.PRI}; background:transparent;'); clock_col.addWidget(self.clock_label)
        self.date_label=QLabel(''); self.date_label.setAlignment(Qt.AlignmentFlag.AlignRight); self.date_label.setFont(QFont('Courier New',7)); self.date_label.setStyleSheet(f'color:{C.TEXT_DIM}; background:transparent;'); clock_col.addWidget(self.date_label); h.addLayout(clock_col)
        root.addWidget(header)
        body=QHBoxLayout(); body.setContentsMargins(0,0,0,0); body.setSpacing(0); root.addLayout(body,1)
        left=QWidget(); left.setFixedWidth(176); left.setStyleSheet(f'background:{C.DARK}; border-right:1px solid {C.BORDER};'); ll=QVBoxLayout(left); ll.setContentsMargins(8,10,8,10); ll.setSpacing(6)
        sys_hdr=QLabel('◈ SYS MONITOR'); sys_hdr.setFont(QFont('Courier New',7,QFont.Weight.Bold)); sys_hdr.setStyleSheet(f'color:{C.PRI}; background:transparent; border-bottom:1px solid {C.BORDER}; padding-bottom:4px;'); ll.addWidget(sys_hdr)
        self.cpu=MetricBar('CPU',C.PRI); self.mem=MetricBar('MEM',C.ACC2); self.disk=MetricBar('DISK',C.GREEN); self.net=MetricBar('NET',C.ACC); self.gpu=MetricBar('GPU','#ff6688')
        self._metric_bars=(self.cpu,self.mem,self.disk,self.net,self.gpu)
        for bar in self._metric_bars: ll.addWidget(bar)
        info=QLabel('UP  ACTIVE\nOS  DESKTOP\nSEC  PAIRED'); info.setFont(QFont('Courier New',8,QFont.Weight.Bold)); info.setStyleSheet(f'color:{C.ACC2}; background:{C.PANEL2}; border:1px solid {C.BORDER}; border-radius:4px; padding:6px;'); ll.addWidget(info)
        ll.addStretch()
        for text,color in (('AI CORE\nACTIVE',C.GREEN),('SEC\nCLEARED',C.PRI),('PROTOCOL\nPAIRING',C.TEXT_DIM)):
            badge=QLabel(text); badge.setAlignment(Qt.AlignmentFlag.AlignCenter); badge.setFont(QFont('Courier New',7,QFont.Weight.Bold)); badge.setStyleSheet(f'color:{color}; background:{C.PANEL2}; border:1px solid {C.BORDER_A}; border-radius:3px; padding:4px;'); ll.addWidget(badge)
        body.addWidget(left)
        center=QWidget(); cv=QVBoxLayout(center); cv.setContentsMargins(0,0,0,0); cv.setSpacing(0)
        self.hud=HudCanvas(assistant_name='J.A.R.V.I.S'); self.hud.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding); cv.addWidget(self.hud,1)
        body.addWidget(center,5)
        right=QWidget(); right.setFixedWidth(272); right.setStyleSheet(f'background:{C.DARK}; border-left:1px solid {C.BORDER};'); rl=QVBoxLayout(right); rl.setContentsMargins(8,8,8,8); rl.setSpacing(6)
        section=QLabel('▸ ACTIVITY LOG'); section.setFont(QFont('Courier New',7,QFont.Weight.Bold)); section.setStyleSheet(f'color:{C.TEXT_MED}; background:transparent;'); rl.addWidget(section)
        self.log=LogWidget(); rl.addWidget(self.log,1)
        sep=QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setStyleSheet(f'color:{C.BORDER};'); rl.addWidget(sep)
        command=QLabel('▸ COMMAND INPUT'); command.setFont(QFont('Courier New',7,QFont.Weight.Bold)); command.setStyleSheet(f'color:{C.TEXT_MED}; background:transparent;'); rl.addWidget(command)
        cmdrow=QHBoxLayout(); self.command_input=QLineEdit(); self.command_input.setPlaceholderText('Type a command or question…'); self.command_input.returnPressed.connect(owner.send); cmdrow.addWidget(self.command_input,1)
        send=QPushButton('▸'); send.setFixedSize(30,30); send.clicked.connect(owner.send); cmdrow.addWidget(send); rl.addLayout(cmdrow)
        interrupt=QPushButton('✋  INTERRUPT  [ESC]'); interrupt.clicked.connect(owner.interrupt); rl.addWidget(interrupt)
        self.mic_button=QPushButton('🎙  MICROPHONE ACTIVE'); self.mic_button.clicked.connect(owner.toggle_mic); rl.addWidget(self.mic_button)
        attach=QPushButton('▣  ATTACHMENTS'); attach.clicked.connect(owner.show_attachments); rl.addWidget(attach)
        body.addWidget(right)
        self.clock_timer=QTimer(self); self.clock_timer.timeout.connect(self.update_clock); self.clock_timer.start(1000); self.update_clock()
        self.metrics_timer=QTimer(self); self.metrics_timer.timeout.connect(self.update_metrics); self.metrics_timer.start(3500); self.update_metrics()
        self.show_login(paired=bool(owner.st.get('paired')), message='Connecting to Mark…' if owner.st.get('paired') else '')
    def _make_login(self,owner):
        page=QWidget(self);page.setObjectName('loginPage')
        outer=QVBoxLayout(page);outer.setContentsMargins(32,22,32,32)
        brand=QHBoxLayout();brand.addStretch()
        name=QLabel('Mark');name.setObjectName('gatewayBrand');name.setStyleSheet('color: #f7f8f8; font-size: 17px; font-weight: bold; letter-spacing: 4px;');brand.addWidget(name)
        dot=QLabel('●');dot.setStyleSheet('color: #16d9f5; font-size: 13px;');brand.addWidget(dot)
        brand.addStretch();outer.addLayout(brand)
        outer.addStretch(1)
        outer.addWidget(GatewayMark(page),0,Qt.AlignmentFlag.AlignHCenter)
        caption=QLabel('COMPANION')
        caption.setStyleSheet('color: #8b959a; letter-spacing: 5px; font-size: 12px; font-weight: bold;')
        outer.addWidget(caption,0,Qt.AlignmentFlag.AlignHCenter)
        outer.addSpacing(20)
        card=QFrame(page);card.setObjectName('gatewayCard');card.setStyleSheet('QFrame#gatewayCard { background-color: #0c1116; border: 1px solid #273239; border-radius: 22px; }');card.setFixedWidth(430)
        box=QVBoxLayout(card);box.setContentsMargins(30,28,30,25);box.setSpacing(13)
        self.gateway_title=QLabel();self.gateway_title.setStyleSheet('color: #f7f8f8; font-size: 24px; font-weight: bold;');box.addWidget(self.gateway_title)
        self.gateway_hint=QLabel();self.gateway_hint.setStyleSheet('color: #9aabb1; font-size: 13px;')
        self.gateway_hint.setWordWrap(True);box.addWidget(self.gateway_hint)
        box.addSpacing(5)
        self.code_label=QLabel('PAIR CODE')
        self.code_label.setStyleSheet('color: #9ad9e0; font-size: 11px; font-weight: bold; letter-spacing: 1px;')
        box.addWidget(self.code_label)
        self.code_input=QLineEdit(card);self.code_input.setObjectName('gatewayInput')
        self.code_input.setStyleSheet('QLineEdit { background: #10191d; border: 1px solid #315861; border-radius: 10px; color: #f7f8f8; font-size: 18px; padding: 10px; } QLineEdit:focus { border: 2px solid #00d4ff; }')
        self.code_input.setPlaceholderText('6-character code');self.code_input.setMaxLength(6)
        self.code_input.setAlignment(Qt.AlignmentFlag.AlignCenter);self.code_input.setFixedHeight(48)
        self.code_input.returnPressed.connect(owner.pair);box.addWidget(self.code_input)
        self.pair_button=QPushButton('PAIR DEVICE');self.pair_button.setObjectName('gatewayPrimary')
        self.pair_button.setStyleSheet('QPushButton { color: #001417; background: #16d9f5; border: none; border-radius: 10px; font-size: 13px; font-weight: bold; } QPushButton:disabled { color: #84999d; background: #193239; }')
        self.pair_button.setFixedHeight(46);self.pair_button.clicked.connect(owner.pair);box.addWidget(self.pair_button)
        self.reconnect_button=QPushButton('RECONNECT');self.reconnect_button.setObjectName('gatewayPrimary')
        self.reconnect_button.setStyleSheet(self.pair_button.styleSheet())
        self.reconnect_button.setFixedHeight(46);self.reconnect_button.clicked.connect(owner.connect);box.addWidget(self.reconnect_button)
        self.gateway_status=QLabel();self.gateway_status.setStyleSheet('color: #9bb0b5; font-size: 12px;')
        self.gateway_status.setWordWrap(True);box.addWidget(self.gateway_status)
        self.new_code_button=QPushButton('Use a new Pair Code')
        self.new_code_button.setObjectName('gatewaySecondary')
        self.new_code_button.setStyleSheet('QPushButton { border: none; color: #9ad9e0; background: transparent; }')
        self.new_code_button.clicked.connect(owner.prepare_new_pair_code)
        box.addWidget(self.new_code_button)
        outer.addWidget(card,0,Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(2)
        return page
    def _ensure_video(self):
        if QVideoWidget is None or QMediaPlayer is None or QAudioOutput is None:
            raise RuntimeError('QtMultimedia is unavailable on this desktop companion')
        if self.video_window is None:
            self.video_window = QVideoWidget()
            self.video_window.setWindowTitle('Mark · Video')
            self.video_window.resize(960, 540)
            self.video_audio = QAudioOutput(self.video_window)
            self.video_player = QMediaPlayer(self.video_window)
            self.video_player.setAudioOutput(self.video_audio)
            self.video_player.setVideoOutput(self.video_window)
            self.video_audio_output = QAudioOutput(self.video_window)
            self.video_audio_player = QMediaPlayer(self.video_window)
            self.video_audio_player.setAudioOutput(self.video_audio_output)
            self.video_player.errorOccurred.connect(lambda *_: self.set_status('Video playback error'))
        return self.video_player

    def show_video(self, source, title='', muted=True, audio_source=''):
        def open_video():
            player = self._ensure_video()
            self.video_window.setWindowTitle(title or 'Mark · Video')
            self.video_audio.setMuted(bool(muted))
            self.video_audio_output.setMuted(bool(muted))
            player.setSource(QUrl.fromUserInput(str(source)))
            player.play()
            if audio_source:
                self.video_audio_player.setSource(QUrl.fromUserInput(str(audio_source)))
                self.video_audio_player.play()
            self.video_window.show()
            self.video_window.raise_()
            self.video_window.activateWindow()
        QTimer.singleShot(0, open_video)

    def stop_video(self):
        if self.video_player is not None:
            self.video_player.stop()
        if self.video_audio_player is not None:
            self.video_audio_player.stop()
        if self.video_window is not None:
            self.video_window.hide()

    def set_video_muted(self, muted):
        if self.video_audio is None:
            raise RuntimeError('no video is playing')
        self.video_audio.setMuted(bool(muted))
        if self.video_audio_output is not None:
            self.video_audio_output.setMuted(bool(muted))

    def video_is_playing(self):
        return bool(self.video_player is not None and self.video_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)

    def show_login(self,paired=False,message=''):
        self.pages.setCurrentWidget(self.login_page)
        self.gateway_title.setText(('Connecting to Mark' if message=='Connecting to Mark…' else 'Reconnect to Mark') if paired else 'Connect to Mark')
        self.gateway_hint.setText(('Your paired desktop is reconnecting.' if message=='Connecting to Mark…' else 'Your desktop identity is saved.') if paired else 'Enter the Pair Code from your Mark server.')
        self.code_label.setVisible(not paired)
        self.code_input.setVisible(not paired)
        self.pair_button.setVisible(not paired)
        self.reconnect_button.setVisible(paired)
        self.reconnect_button.setEnabled(message!='Connecting to Mark…')
        self.new_code_button.setVisible(paired)
        self.gateway_status.setText(message)
        self.gateway_status.setVisible(bool(message))
        if not paired and self.isVisible():self.code_input.setFocus()
    def show_connecting(self):
        self.show_login(paired=True,message='Connecting to Mark…')
    def show_dashboard(self):
        self.pages.setCurrentWidget(self.dashboard_page)
        self.set_status('Connected · voice on client')
    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()
    def show_connection_error(self,message):
        self.show_login(paired=bool(self.owner.st.get('paired')),message=message)
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
    def update_clock(self):
        import time
        self.clock_label.setText(time.strftime('%H:%M:%S'))
        self.date_label.setText(time.strftime('%a %d %b %Y'))

    def update_metrics(self):
        values=(psutil.cpu_percent(), psutil.virtual_memory().percent, psutil.disk_usage(str(__import__('pathlib').Path.home())).percent, 0.0, 0.0)
        for bar, value in zip(self._metric_bars, values):
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
        self.setWindowTitle('Attachments · Mark'); self.resize(600, 430)
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
