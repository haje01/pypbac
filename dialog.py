from tkinter import *
import os

class Dialog(Toplevel):

    def __init__(self, parent, title = None):

        Toplevel.__init__(self, parent)
        self.transient(parent)

        if title:
            self.title(title)

        self.parent = parent

        self.result = None

        body = Frame(self)
        self.initial_focus = self.body(body)
        body.pack(padx=5, pady=5)

        self.buttonbox()

        self.grab_set()

        if not self.initial_focus:
            self.initial_focus = self

        self.protocol("WM_DELETE_WINDOW", self.cancel)

        self.geometry("+%d+%d" % (parent.winfo_rootx()+50,
                                  parent.winfo_rooty()+50))

        self.initial_focus.focus_set()

        self.wait_window(self)

    #
    # construction hooks

    def body(self, master):
        # create dialog body.  return widget that should have
        # initial focus.  this method should be overridden

        pass

    def buttonbox(self):
        # add standard button box. override if you don't want the
        # standard buttons

        box = Frame(self)

        w = ttk.Button(box, text="OK", width=10, command=self.ok, default=ACTIVE)
        w.pack(side=LEFT, padx=5, pady=5)
        w = ttk.Button(box, text="Cancel", width=10, command=self.cancel)
        w.pack(side=LEFT, padx=5, pady=5)

        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

        box.pack()

    #
    # standard button semantics

    def ok(self, event=None):

        if not self.validate():
            self.initial_focus.focus_set() # put focus back
            return

        self.withdraw()
        self.update_idletasks()

        self.apply()

        self.cancel()

    def cancel(self, event=None):

        # put focus back to the parent window
        self.parent.focus_set()
        self.destroy()

    #
    # command hooks

    def validate(self):

        return 1 # override

    def apply(self):

        pass # override


class ModelessDlg:

    def __init__(self, parent, text, width=220, height=90, x=70, y=150):
        top = self.top = Toplevel(parent)
        px = parent.winfo_x()
        py = parent.winfo_y()
        top.geometry("%dx%d%+d%+d" % (width, height, px + x, py + y))        
        Label(top, text=text).pack(expand=True, fill='both')


class ModalDlg:

    def __init__(self, parent, title, width, height, x, y):
        top = self.top = Toplevel(parent)
        px = parent.winfo_x()
        py = parent.winfo_y()
        top.geometry("%dx%d%+d%+d" % (width, height, px + x, py + y))        
        top.details_expanded = False
        top.resizable(False, False)
        top.title(title)


class ConfirmDlg(ModalDlg):

    def __init__(self, parent, title, message, width=250, height=100, x=60, y=150, type="information"):
        """Confirm 대화창 초기화

        Args:
            parent: 부모 윈도우
            title: 타이틀
            message: 메시지
            type: 아이콘 타입 (warning, error, information, question 중 하나)

        """
        super().__init__(parent, title, width, height, x, y)
        image = "::tk::icons::{}".format(type)
        self.frame = Frame(self.top)
        Label(self.frame, image=image).pack(side=LEFT)
        Label(self.frame, text=message).pack(side=LEFT)
        self.frame.pack(side=TOP, pady=12)
        Button(self.top, text="OK", command=self.top.master.destroy, width=8).pack(side=TOP)


class VersionDlg(ModalDlg):

    def __init__(self, parent, title, rel_title, rel_lines, width=330, height=180, x=20, y=50):
        """버전 대화창 초기화

        Args:
            parent: 부모 윈도우
            title: 타이틀
            lines: 공지 (멀티 라인)
            message: 메시지

        """
        super().__init__(parent, title, width, height, x, y)
        self.top.resizable(True, True)

        self.frame = LabelFrame(self.top, text=rel_title)
        self.text = Text(self.frame, wrap="none", height=3.5, background=self.frame.cget('bg'), bd=0)
        self.text.grid_propagate(False)
        self.vsb = Scrollbar(self.frame, orient="vertical", command=self.text.yview)
        self.vsb.pack(side='right', fill='y')
        self.hsb = Scrollbar(self.frame, orient="horizontal", command=self.text.xview)
        self.hsb.pack(side="bottom", fill="x")
        self.text.configure(xscrollcommand=self.hsb.set, yscrollcommand=self.vsb.set)
        for line in rel_lines.split('\n'):
            self.text.insert(END, line.strip() + '\n')
                         
        self.text.pack(fill='both', expand=True, padx=15, pady=(5, 20))
        self.text['state'] = 'disabled'
        self.frame.pack(side=TOP, fill='both', expand=True, padx=20, pady=(10, 0))

        Button(self.top, text="OK", command=self.top.destroy, width=8).pack(side=BOTTOM, pady=10)


class OkCancelDlg(ModalDlg):

    def __init__(self, parent, title, message, width=250, height=100, x=60, y=150, type="information"):
        """Ok/Cancel 대화창 초기화

        Args:
            parent: 부모 윈도우
            title: 타이틀
            message: 메시지
            type: 아이콘 타입 (warning, error, information, question 중 하나)

        """
        super().__init__(parent, title, width, height, x, y)
        image = "::tk::icons::{}".format(type)
        self.frame = Frame(self.top)
        Label(self.frame, image=image).pack(side=LEFT)
        Label(self.frame, text=message).pack(side=LEFT)
        self.frame.pack(side=TOP, pady=12)
        self.cframe = Frame(self.top)
        Button(self.cframe, text="OK", command=self.top.destroy, width=8).pack(side=LEFT, padx=10)
        Button(self.cframe, text="Cancel", command=self.top.destroy, width=8).pack(side=LEFT, padx=10)
        self.cframe.pack(side=TOP)