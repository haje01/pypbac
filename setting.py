"""설정 GUI."""
import time
from configparser import ConfigParser
from copy import deepcopy

from tkinter import *
from tkinter import ttk
from tkinter import messagebox
from tkinter.simpledialog import askstring
from pyathena import connect

from datepicker import Datepicker
import tkSimpleDialog
from util import *

WIN_WIDTH = 370
WIN_HEIGHT = 720
NB_WIDTH = 330
NB_HEIGHT = 630

databases = cursor = None
cfg = ConfigParser()
org_cfg = None
profiles = {}


def save_config(cfg):
    global org_cfg

    info("Save config file to {}".format(cfg_path))
    with open(cfg_path, 'w') as cfgfile:
        cfg.write(cfgfile)
    org_cfg = deepcopy(cfg)


class AWSConfigDlg(tkSimpleDialog.Dialog):

    def body(self, master):

        self.need_connect = False

        Label(master, text="Access Key :").grid(row=0)
        Label(master, text="Secret Key :").grid(row=1)
        Label(master, text="S3 Stage Dir :").grid(row=2)

        self.acval = StringVar()
        self.ackey = Entry(master, textvariable=self.acval, width=30)
        self.scval = StringVar()
        self.sckey = Entry(master, textvariable=self.scval, width=30)
        self.sckey.configure(show="*")
        self.s3val = StringVar()
        self.s3dir = Entry(master, textvariable=self.s3val, width=30)

        try:
            self.acval.set(cfg['aws']['access_key'])
            self.scval.set(cfg['aws']['secret_key'])
            self.s3val.set(cfg['aws']['s3_stage_dir'])
        except Exception as e:
            pass

        self.ackey.grid(row=0, column=1)
        self.sckey.grid(row=1, column=1)
        self.s3dir.grid(row=2, column=1)
        return self.ackey # initial focus

    def validate(self):
        access_key = self.ackey.get()
        secret_key = self.sckey.get()
        s3_stage_dir = self.s3dir.get()

        if len(access_key) == 0:
            messagebox.showerror("Error", "Access Key를 입력해주세요.")
            self.initial_focus = self.ackey
            return 0

        if len(secret_key) == 0:
            messagebox.showerror("Error", "Secret Key를 입력해주세요.")
            self.initial_focus = self.sckey
            return 0

        if len(s3_stage_dir) == 0:
            messagebox.showerror("Error", "S3 Stage 경로를 입력해주세요.")
            self.initial_focus = self.s3dir
            return 0
        return 1

    def apply(self):
        global cfg
        cfg['aws'] = {}
        cfg['aws']['access_key'] = self.ackey.get()
        cfg['aws']['secret_key'] = self.sckey.get()
        cfg['aws']['s3_stage_dir'] = self.s3dir.get()
        self.need_connect = org_cfg != cfg
        save_config(cfg)


def get_current_profile():
    pt = notebook.select()
    tab = notebook.tab(pt)
    return profiles[tab['text']]


def on_ttype():
    curpro = get_current_profile()
    curpro.switch_absrel_frame()


def disable_controls():
    global prev_tab, win

    for pro in profiles.values():
        pro.disable_controls()
    for ctrl in global_disable_targets:
        ctrl['state'] = 'disabled'
    
    pt = notebook.select()
    if len(pt) > 0:
        prev_tab = pt

    # for item in notebook.tabs():
    #     notebook.tab(item, state='disabled')
    win.update_idletasks()


def on_db_sel(eobj):
    set_wait_cursor()
    disable_controls()

    def _db_set():
        curpro = get_current_profile()
        curpro.db_set()
        enable_controls()
        unset_wait_cursor()

    win.after(10, _db_set)


def on_all_table():
    """테이블 전체 선택."""
    curpro = get_current_profile()
    for cv in curpro.tbl_cvs:
        cv.set(1)
    on_check()
    

def on_no_table():
    """테이블 전체 지우기."""
    curpro = get_current_profile()
    for cv in curpro.tbl_cvs:
        cv.set(0)
    on_check()
    

def on_del_cache():
    curpro = get_current_profile()
    del_cache(curpro.name)
    messagebox.showinfo("Info", "프로파일 '{}' 의 캐쉬를 제거했습니다.".format(curpro.name))


def on_save():
    """설정 저장"""
    global cfg, profiles
    set_wait_cursor()
    disable_controls()

    def _save(cfg):
        _cfg = ConfigParser()
        _cfg['aws'] = cfg['aws']

        # 설정 검증
        for pro in profiles.values():
            pcfg = pro.validate_cfg()
            if pcfg is None:
                return
            sname = "profile.{}".format(pro.name)
            _cfg[sname] = pcfg            

        cfg = _cfg

        save_config(cfg)
        enable_controls()
        unset_wait_cursor()
        win.destroy()

    win.after(100, lambda: _save(cfg))


class Profile:

    def __init__(self, name, win, notebook, proidx):

        global pro
        self.name = name
        self.selected_tables = {}
        self.first_sel_db = None
        self.proidx = proidx

        #
        # Document Data
        #
        warning("Init document data")
        self.ttype = StringVar()
        self.ttype.set('rel')
        self.lct_val = IntVar()
        self.lct_val.set(6)
        self.rel_bg_var = IntVar()
        self.rel_bg_var.set(1)
        self.rel_off_var = IntVar()
        self.rel_off_var.set(1)
        self.st_dp_val = self.ed_dp_val = None
        self.db_val = StringVar()

        #
        # UI
        #
        self.notebook = notebook
        self.pro_frame = Frame(win)
        notebook.add(self.pro_frame, text=name)
        self.abs_frame = LabelFrame(self.pro_frame, text="날자 선택")
        self.rel_frame = LabelFrame(self.pro_frame, text="범위 선택")

        # 날자 타입
        self.ttype_frame = Frame(self.pro_frame)
        self.rel_rbt = Radiobutton(self.ttype_frame, text="상대 시간", variable=self.ttype, value="rel", command=on_ttype)
        self.rel_rbt.pack(side=LEFT, expand=True, padx=(20, 10))
        self.abs_rbt = Radiobutton(self.ttype_frame, text="절대 시간", variable=self.ttype, value="abs", command=on_ttype)
        self.abs_rbt.pack(side=LEFT, expand=True, padx=(10, 20))
        self.ttype_frame.pack(side=TOP, pady=(20, 0))

        # 상대 시간
        self.rel_bg_etr = Entry(self.rel_frame, textvariable=self.rel_bg_var, width=5, justify=CENTER)
        self.rel_bg_etr.pack(side=LEFT, padx=(15, 5), pady=10)
        Label(self.rel_frame, text="일 전부터").pack(side=LEFT, pady=10)
        self.rel_off_etr = Entry(self.rel_frame, textvariable=self.rel_off_var, width=5, justify=CENTER)
        self.rel_off_etr.pack(side=LEFT, padx=(10, 5), pady=10)
        Label(self.rel_frame, text="일치 데이터").pack(side=LEFT, padx=(0, 15), pady=10)
        self.pack_rel_frame()

        # 절대 시간 
        self.dts_frame = Frame(self.abs_frame)
        st_lbl = Label(self.dts_frame, justify="left", text="시작일")
        st_lbl.grid(row=0, column=0, stick=W, padx=(10, 20), pady=3)
        self.st_dp = Datepicker(self.dts_frame)
        self.st_dp.grid(row=0, column=1, padx=(10, 20), pady=3)
        self.dts_frame.pack(side=TOP)

        self.dte_frame = Frame(self.abs_frame)
        ed_lbl = Label(self.dte_frame, justify="left", text="종료일")
        ed_lbl.grid(row=0, column=0, stick=W, padx=(10, 20), pady=3)
        self.ed_dp = Datepicker(self.dte_frame)
        self.ed_dp.grid(row=0, column=1, padx=(10, 20), pady=3)
        self.dte_frame.pack(side=TOP, pady=(7, 10))
        self.pack_abs_frame()

        # 날자 이후 UI프레임
        self.after_dt_frame = Frame(self.pro_frame)
        self.sel_frame = Frame(self.after_dt_frame)

        # DB 선택 UI
        self.db_frame = LabelFrame(self.sel_frame, text="DB 선택")
        self.db_combo = ttk.Combobox(self.db_frame, width=20, textvariable=self.db_val, state="readonly")
        self.cur_db = None

        self.db_combo.bind("<<ComboboxSelected>>", on_db_sel)
        self.db_combo.pack(padx=10, pady=(10,))
        self.db_frame.pack(side=TOP)

        # Table 선택 UI
        self.tbl_frame = LabelFrame(self.sel_frame, text="테이블 선택")
        self.tbl_text = Text(self.tbl_frame, wrap="none", height=10, background=self.tbl_frame.cget('bg'), bd=0)
        self.tbl_text.grid_propagate(False)
        self.tbl_vsb = Scrollbar(self.tbl_frame, orient="vertical", command=self.tbl_text.yview)
        self.tbl_text.configure(yscrollcommand=self.tbl_vsb.set)
        self.tbl_vsb.pack(side="right", fill="y")
        self.tbl_text.pack(fill='both', expand=True, padx=15, pady=(5, 20))

        self.tbl_frame.pack(side=TOP, fill=None, expand=False, padx=20, pady=(10, 5))
        self.sel_frame.pack(side=TOP)
        self.tbl_ckbs = []
        self.tbl_cvs = []

        # 테이블 전체 선택/취소
        self.tbb_frame = Frame(self.after_dt_frame)
        self.all_btn = ttk.Button(self.tbb_frame, text="전체 선택", width=8, command=on_all_table)
        self.all_btn.pack(side=LEFT, expand=YES)
        self.none_btn = ttk.Button(self.tbb_frame, text="전체 취소", width=8, command=on_no_table)
        self.none_btn.pack(side=LEFT, expand=YES)
        self.tbb_frame.pack(fill=BOTH, expand=YES)

        self.switch_absrel_frame()

        # 선택된 대상
        self.target_frame = LabelFrame(self.after_dt_frame, text="모든 선택된 대상")
        self.target_text = Text(self.target_frame, wrap="none", height=3.5, background=self.target_frame.cget('bg'), bd=0)
        self.target_text.grid_propagate(False)
        self.target_vsb = Scrollbar(self.target_frame, orient="vertical", command=self.target_text.yview)
        self.target_vsb.pack(side='right', fill='y')
        self.target_hsb = Scrollbar(self.target_frame, orient="horizontal", command=self.target_text.xview)
        self.target_hsb.pack(side="bottom", fill="x")
        self.target_text.configure(xscrollcommand=self.target_hsb.set, yscrollcommand=self.target_vsb.set)
        self.target_text.pack(fill='both', expand=True, padx=15, pady=(5, 20))
        self.target_text['state'] = 'disabled'
        self.target_frame.pack(side=TOP, fill=None, expand=False, padx=20, pady=(10, 0))

        self.update_targets_text()

        self.lct_frame = Frame(self.after_dt_frame)
        Label(self.lct_frame, text="로컬 캐쉬 유효 시간:").pack(side=LEFT)
        self.lct_etr = Entry(self.lct_frame, textvariable=self.lct_val, width=3, justify="center")
        self.lct_etr.pack(side=LEFT, padx=(5, 2))
        Label(self.lct_frame, text="시간").pack(side=LEFT)
        self.lct_frame.pack(side=TOP, pady=(10, 0))

        self.confirm_frame = Frame(self.after_dt_frame)

        self.flush_btn = ttk.Button(self.confirm_frame, text="로컬 캐쉬 제거", width=15, command=on_del_cache)
        self.flush_btn.pack(side=LEFT, expand=YES, padx=10, pady=10)

        self.confirm_frame.pack(fill=BOTH, expand=YES)

        self.disable_targets = [self.st_dp, self.ed_dp, self.all_btn, self.none_btn, self.lct_etr, 
                                self.db_combo, self.rel_rbt, self.abs_rbt, self.rel_bg_etr, self.rel_off_etr, self.flush_btn]

    def set_databases(self, databases):
        self.db_combo['values'] = databases
        # 첫 번재 DB 선택
        db_idx = self.find_first_db_idx()
        info("set_databases set db idx {}".format(db_idx))
        self.first_sel_db = self.db_combo.current(db_idx)

    def db_set(self):
        assert len(self.db_combo['values']) > 0
        self.cur_db = self.db_combo.get()
        info("Read tables from '{}'.".format(self.cur_db))
        self.fill_tables(self.cur_db)

    def find_first_db_idx(self):
        for idx, db in enumerate(databases):
            if self.first_sel_db == db:
                return idx
        return 0

    def set_wait_cursor(self):
        if self.tbl_text is not None:
            self.tbl_text.config(cursor='wait')

    def unset_wait_cursor(self):
        if self.tbl_text is not None:
            self.tbl_text.config(cursor='')

    def pack_rel_frame(self):
        self.rel_frame.pack(side=TOP, pady=7)

    def pack_abs_frame(self):
        self.abs_frame.pack(side=TOP, pady=7)

    def switch_absrel_frame(self):
        tval = self.ttype.get()
        self.after_dt_frame.pack_forget()
        if tval == 'rel':
            self.abs_frame.pack_forget()
            self.pack_rel_frame()
        else:
            self.rel_frame.pack_forget()        
            self.pack_abs_frame()
        self.after_dt_frame.pack(side=TOP)

    def apply_profile_cfg(self, pcfg):
        """읽은 프로파일 설정을 적용."""
        info("apply_profile_cfg")
        self.org_pcfg = deepcopy(pcfg)
        
        # 대상 시간
        if 'ttype' in pcfg:
            self.ttype.set(pcfg['ttype'])
            on_ttype()
            
        if 'before' in pcfg:
            self.rel_bg_var.set(int(pcfg['before']))
        if 'offset' in pcfg:
            self.rel_off_var.set(int(pcfg['offset']))

        if 'start' in pcfg:
            self.st_dp_val = parse(pcfg['start']).date()
        if 'end' in pcfg:
            self.ed_dp_val = parse(pcfg['end']).date()

        if self.st_dp_val is not None:
            self.st_dp.current_date = self.st_dp_val
        if self.ed_dp_val is not None:
            self.ed_dp.current_date = self.ed_dp_val

        # DB를 순회
        for key in pcfg.keys():
            if not key.startswith('db_'):
                continue

            db = key[3:]
            tables = eval(pcfg[key])
            if self.first_sel_db is None and len(tables) > 0:
                self.first_sel_db = db
            self.selected_tables[db] = tables

        if 'cache_valid_hour' in pcfg:
            cache_valid_hour = int(pcfg['cache_valid_hour'])
            self.lct_val.set(cache_valid_hour)

        self.update_targets_text()

    def fill_tables(self, db):
        info("fill_tables for {}".format(db))

        tables = get_tables(db)
        # 이전에 선택된 테이블들 
        if db in self.selected_tables:
            selected = self.selected_tables[db]
            info("  selected: {}".format(selected))
        else:
            selected = []

        num_tbl = len(tables)
        for ckbs in self.tbl_ckbs:
            ckbs.destroy()
        self.tbl_ckbs = []
        self.tbl_cvs = []
        self.tbl_text.configure(state='normal')
        self.tbl_text.delete('1.0', END)

        for i, tbl in enumerate(tables):
            cv = IntVar()
            if tbl in selected:
                cv.set(1)
            ckb = Checkbutton(self.tbl_text, text=tbl, variable=cv, command=on_check)
            self.tbl_text.window_create("end", window=ckb)
            self.tbl_text.insert("end", "\n")
            self.tbl_ckbs.append(ckb)
            self.tbl_cvs.append(cv)

        self.tbl_text.configure(state='disabled')
        self.tbl_frame.update()

    def update_sel_tables(self):
        """DB의 선택된 테이블 기억."""
        info("update_sel_tables for {}".format(self.cur_db))
        selected = []
        for i, cv in enumerate(self.tbl_cvs):
            if cv.get() == 1:
                selected.append(self.tbl_ckbs[i]['text'])
        self.selected_tables[self.cur_db] = selected

    def validate_cfg(self):
        """프로파일 설정 값 확인.
        
        프로파일 UI에 설정된 값들을 확인하고, dict 넣어 반환
        
        Returns:
            dict
        """
        info("validate_cfg")
        pcfg = {}  # 프로파일 설정

        if self.ttype.get() == 'rel':
            # 상대 시간
            before = self.rel_bg_var.get()
            offset = self.rel_off_var.get()
            if before <= 0:
                messagebox.showerror("Error", "몇 일 전부터 시작할지 양의 정수로 지정해 주세요.")
                return
            elif offset <= 0:
                messagebox.showerror("Error", "몇 일치 데이터를 가져올지 양의 정수로 지정해 주세요.")
                return
            pcfg['ttype'] = 'rel'
            pcfg['before'] = str(before)
            pcfg['offset'] = str(offset)
        else:
            # 절대 시간
            start = self.st_dp.get()
            end = self.ed_dp.get()
            db_name = self.db_combo.get()

            if len(start) == 0:
                messagebox.showerror("Error", "시작일을 선택해주세요.")
                return
            elif len(end) == 0:
                messagebox.showerror("Error", "종료일을 선택해주세요.")
                return
            elif len(db_name) == 0:
                messagebox.showerror("Error", "선택된 DB가 없습니다.")
                return

            start = parse(start).date()
            end = parse(end).date()
            if start > end:
                messagebox.showerror("Error", "종료일이 시작일보다 빠릅니다.")
                return
            pcfg['ttype'] = 'abs'
            pcfg['start'] = str(start)
            pcfg['end'] = str(end)


        # 가져올 행수를 체크
        tbl_cnt = 0
        for db, tbls in self.selected_tables.items():
            for tbl in tbls:
                tbl_cnt += 1
                if self.ttype.get() == 'rel':
                    cnt = get_query_rows_rel(cursor, db, tbl, before, offset, None)
                else:
                    cnt = get_query_rows_abs(cursor, db, tbl, start, end, None)
                info("'{}' '{}' has {} rows".format(db, tbl, cnt))
                if cnt > WARN_ROWS:
                    rv = messagebox.askquestion("경고", "{} DB의 {} 테이블의 행수가 매우 큽니다 ({:,} 행)."
                                                "\n정말 가져오겠습니까?".format(db, tbl, cnt))
                    if rv != 'yes':
                        return

        if tbl_cnt == 0:
            messagebox.showerror("Error", "선택된 테이블이 없습니다.")
            return

        # 선택된 테이블 기억
        for db in self.selected_tables.keys():
            tables = self.selected_tables[db]
            if len(tables) > 0:
                pcfg["db_" + db] = str(tables)

        # 캐쉬 유효 시간
        cache_valid_hour = self.lct_val.get()
        if cache_valid_hour <= 0:
            messagebox.showerror("Error", "캐쉬 수명은 최소 0보다 커야 합니다.")
            return
        pcfg['cache_valid_hour'] = str(self.lct_val.get())

        return pcfg

    def update_targets_text(self):
        """선택된 테이블들 표시."""
        self.target_text['state'] = 'normal'
        self.target_text.delete('1.0', END)
        for db, tables in self.selected_tables.items():
            if len(tables) == 0:
                continue
            text = "{} ({})\n".format(db, ','.join(tables))
            self.target_text.insert(END, text)
        self.target_text['state'] = 'disabled'

    def disable_controls(self):
        for ctrl in (self.disable_targets + self.tbl_ckbs):
            ctrl['state'] = 'disabled'
        self.tbl_text.configure(state='disabled')

    def enable_controls(self):
        for ctrl in (self.disable_targets + self.tbl_ckbs):
            ctrl['state'] = 'normal'
        self.db_combo['state'] = 'readonly'
        self.tbl_text.configure(state='normal')


info("Construct GUI.")
win = Tk()
win.title("Athena 가져오기 설정")
win.geometry("{}x{}+100+100".format(WIN_WIDTH, WIN_HEIGHT))


def add_profile(win, pro_name):
    proidx = len(profiles)
    pro = Profile(pro_name, win, notebook, proidx)
    if databases is not None:
        pro.set_databases(databases)
    profiles[pro_name] = pro
    notebook.select(proidx)
    return pro


def profile_exists(name):
    return name in profiles


def on_add_profile():
    pro_name = askstring("프로파일 생성", "새로운 프로파일 이름?", parent=win)
    if profile_exists(pro_name):
        messagebox.showerror("에러", "같은 이름의 프로파일이 이미 존재합니다.")
        return
    if pro_name is not None and len(pro_name) > 0:
        add_profile(win, pro_name)


def on_del_profile():
    if len(profiles) == 1:
        messagebox.showerror("에러", "적어도 하나 이상의 프로파일이 필요합니다.")
        return
    tab = notebook.select()
    pro_name = notebook.tab(tab)['text']
    yes = messagebox.askokcancel("프로파일 삭제", "'{}' 프로파일을 지우시겠습니까?".format(pro_name), parent=win)
    if yes:
        notebook.forget(tab)
        del profiles[pro_name]


pm_frame = Frame(win)
pm_frame.pack(side=RIGHT, fill=Y, padx=3, pady=5)

addp_btn = Button(pm_frame, text='+', command=on_add_profile, width=1)
addp_btn.pack(side=TOP)
delp_btn = Button(pm_frame, text='-', command=on_del_profile, width=1)
delp_btn.pack(side=TOP)


def set_wait_cursor():
    win.config(cursor='wait')
    curpro = get_current_profile()
    curpro.set_wait_cursor()
    win.update_idletasks()


def unset_wait_cursor():
    win.config(cursor='')
    curpro = get_current_profile()
    curpro.unset_wait_cursor()


def show_aws_config():
    return AWSConfigDlg(win, title="AWS 계정")


def iter_profile_sect(cfg):
    for key in cfg.keys():
        if key.startswith('profile.'):
            yield key


notebook = ttk.Notebook(win, width=NB_WIDTH, height=NB_HEIGHT)
notebook.pack(pady=(15, 0), anchor=NE)

# 설정 읽기
need_aws = False
if os.path.isfile(cfg_path):
    try:
        cfg, _ = load_config()
        # 모든 프로파일 설정
        for sname in iter_profile_sect(cfg):
            pro_name = sname[8:]
            pcfg = cfg[sname]
            pro = add_profile(win, pro_name)
            pro.apply_profile_cfg(pcfg)
    except Exception as e:
        error(str(e))
        messagebox.showerror("에러", "설정 읽기 오류입니다.\n{} 파일 확인 후 시작해주세요.".format(CFG_FILE))
        sys.exit()

    if 'aws' not in cfg.sections():
        messagebox.showwarning("경고", "AWS 계정 설정이 없습니다. 먼저 설정 해주세요.")        
        need_aws = True
else:
    messagebox.showwarning("경고", "설정 파일이 없습니다. 먼저 AWS 계정부터 설정 해주세요.")
    need_aws = True


def get_tables(db):
    _tables = cursor.execute('show tables in {}'.format(db)).fetchall()
    return [r[0] for r in _tables]


notebook.select(0)
pro_names = list(profiles.keys())


def on_check():
    curpro = get_current_profile()
    curpro.update_sel_tables()
    curpro.update_targets_text()


def on_aws():
    d = show_aws_config()
    if d.need_connect:
        try_connect()


confirm_frame = Frame(win)

aws_btn = ttk.Button(confirm_frame, text="AWS 계정", width=10, command=on_aws)
aws_btn.pack(side=LEFT, expand=YES, padx=(20, 7), pady=10)
save_btn = ttk.Button(confirm_frame, text="저장 후 종료", width=15, command=on_save)
save_btn.pack(side=LEFT, expand=YES, padx=10, pady=10)

confirm_frame.pack(fill=BOTH, expand=YES)


global_disable_targets = [aws_btn, save_btn]

# for sname in iter_profile_sect(cfg):
#     pname = sname[8:]
#     pro = profiles[pname]
#     on_db_sel(None)


def enable_controls():
    for pro in profiles.values():
        pro.enable_controls()

    for ctrl in global_disable_targets:
        ctrl['state'] = 'normal'

    # for item in notebook.tabs():
    #     notebook.tab(item, state='normal')
    notebook.select(prev_tab)


class ModelessDlg:

    def __init__(self, parent, text):
        top = self.top = Toplevel(parent)
        x = win.winfo_x()
        y = win.winfo_y()
        top.geometry("%dx%d%+d%+d" % (220, 90, x + 80, y + 160))        
        Label(top, text=text).pack(expand=True, fill='both')


def try_connect():
    global cursor

    # 설정 정보를 이용해 접속
    set_wait_cursor()
    disable_controls()

    wait_dlg = ModelessDlg(win, "접속 중입니다...")

    def _connect(cfg):
        global conn, cursor, databases
        try:
            info("Connect.")
            conn = connect(aws_access_key_id=cfg['aws']['access_key'],
                aws_secret_access_key=cfg['aws']['secret_key'],
                s3_staging_dir=cfg['aws']['s3_stage_dir'],
                region_name='ap-northeast-2')

            cursor = conn.cursor()
            databases = [rv[0] for rv in cursor.execute('show databases').fetchall()]

        except Exception as e:
            error("=== DB Error Message ===")
            error(str(e))
            messagebox.showerror("에러", "DB 접속 에러. AWS 설정을 확인해 주세요.")
            aws_btn['state'] = 'normal'
        else:
            warning("Connect success.")
            enable_controls()
        finally:
            wait_dlg.top.destroy()
            unset_wait_cursor()

    win.after(100, lambda: _connect(cfg))
    win.wait_window(wait_dlg.top)

    while databases is None :
        win.update()
        time.sleep(1)


if 'win' not in sys.platform:
    style = ttk.Style()
    style.theme_use('clam')

if not need_aws:
    try_connect()
    # self.first_sel_db = db_combo.current(find_first_db_idx())
else:
    disable_controls()
    aws_btn['state'] = 'normal'


# 모든 프로파일에 DB 설정
set_wait_cursor()
disable_controls()

for k, pro in profiles.items():
    pro.set_databases(databases)

def _db_set():
    for sname in iter_profile_sect(cfg):
        pname = sname[8:]
        pro = profiles[pname]
        pro.db_set()
        
    enable_controls()
    unset_wait_cursor()


win.after(10, _db_set)


# def on_closing():
#     unsaved = []
#     for pro in profiles.values():
#         if pro.unsaved:
#             unsaved.append(pro.text)

#     if len(unsaved) > 0:
#         upros = unsaved.join(', ')
#         msg = "프로파일을 저장하지 않았습니다.\n정말 종료하시겠습니까?".format(upros)
#         if messagebox.askokcancel("종료", msg):
#         win.destroy()

# win.protocol("WM_DELETE_WINDOW", on_closing)


win.mainloop()

