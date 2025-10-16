#!/usr/bin/env python3
import os, sqlite3, csv, io, requests
from datetime import datetime
import ttkbootstrap as ttk
import tkinter as tk

try:
    from rapidfuzz import fuzz, process
    HAVE_RF=True
except Exception:
    import difflib
    HAVE_RF=False

BASE_DIR=os.path.dirname(os.path.abspath(__file__))
DB_PATH=os.path.join(BASE_DIR,"paket.db")
os.makedirs(BASE_DIR,exist_ok=True)

conn=sqlite3.connect(DB_PATH,check_same_thread=False)
c=conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS packages(
  sendungsnr TEXT PRIMARY KEY,
  zone TEXT,
  received_at TEXT DEFAULT CURRENT_TIMESTAMP,
  name TEXT
)""")
c.execute("""CREATE TABLE IF NOT EXISTS directory(
  sendungsnr TEXT PRIMARY KEY,
  name TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
conn.commit()

def ensure_col(tab,col):
    try:c.execute(f"SELECT {col} FROM {tab} LIMIT 1")
    except Exception:
        c.execute(f"ALTER TABLE {tab} ADD COLUMN {col} TEXT");conn.commit()
ensure_col("packages","name")

CSV_URL="https://nextcloud.aralbruehl.de/public.php/dav/files/mJAaPjgBycC7d7y/hermes_final.csv"

def sync_directory():
    try:
        r=requests.get(CSV_URL,timeout=10);r.raise_for_status()
        content=io.StringIO(r.text);reader=csv.DictReader(content)
        count=0
        for row in reader:
            sn=(row.get("sendungsnr") or row.get("Sendungsnummer") or row.get("SN") or "").strip()
            nm=(row.get("name") or row.get("Name") or "").strip()
            if not sn:continue
            c.execute("REPLACE INTO directory(sendungsnr,name,updated_at) VALUES(?,?,?)",
                      (sn,nm,datetime.now().isoformat(timespec="seconds")));count+=1
        conn.commit();log(f"CSV aktualisiert ({count} Einträge)")
    except Exception as e:log(f"CSV Sync-Fehler: {e}")

def periodic_sync():
    sync_directory();app.after(30000,periodic_sync)

ARAL_BLUE="#0078D7";ARAL_RED="#D00000";WHITE="#FFFFFF";GREEN="#009E00"

active_zone=None;einbuchen_mode=False;session_count=0
zone_buttons={};warn_blink=False

def log(msg):
    ts=datetime.now().strftime("%H:%M:%S")
    log_list.insert(0,f"[{ts}] {msg}")
    if log_list.size()>400:log_list.delete(400,tk.END)

def rf_score(a,b):
    if HAVE_RF:return max(fuzz.token_set_ratio(a,b),fuzz.partial_ratio(a,b))
    else:
        import difflib;return int(difflib.SequenceMatcher(None,a.lower(),b.lower()).ratio()*100)

def best_directory_match(sn):
    rows=c.execute("SELECT sendungsnr,name FROM directory").fetchall()
    if not rows:return None,None,[]
    if HAVE_RF:
        choices=[r[0] for r in rows];res=process.extract(sn,choices,scorer=fuzz.WRatio,limit=10)
        best=res[0] if res else None;near=[(choices[i[2]],i[1]) for i in res if i[1]>=85] if res else []
        if best and best[1]>=90:
            idx=choices.index(best[0]);return rows[idx][0],rows[idx][1],near
        return None,None,near
    else:
        ratios=[(r[0],rf_score(sn,r[0])) for r in rows];ratios.sort(key=lambda x:x[1],reverse=True)
        best=ratios[0] if ratios else None;near=[x for x in ratios if x[1]>=85]
        if best and best[1]>=90:
            nm=c.execute("SELECT name FROM directory WHERE sendungsnr=?",(best[0],)).fetchone()
            return best[0],nm[0] if nm else None,near
        return None,None,near

def merge_near_packages(near,keep_sn,keep_name,zone):
    for other,_ in near:
        if other!=keep_sn:c.execute("DELETE FROM packages WHERE sendungsnr=?",(other,))
    ts=datetime.now().isoformat(timespec="seconds")
    c.execute("REPLACE INTO packages(sendungsnr,zone,received_at,name) VALUES(?,?,?,?)",
              (keep_sn,zone,ts,keep_name));conn.commit()

def blink_warn():
    global warn_blink
    if not warn_label.winfo_ismapped():return
    warn_label.config(fg=ARAL_RED if warn_blink else WHITE)
    warn_blink=not warn_blink;app.after(400,blink_warn)

def show_zone_warn():
    if not warn_label.winfo_ismapped():
        warn_label.place(x=150,y=60);blink_warn()

def hide_zone_warn():
    if warn_label.winfo_ismapped():warn_label.place_forget()

def update_counter_label():
    counter_lbl.config(text=f"Eingebucht: {session_count}")
    color=ARAL_RED if session_count==0 else GREEN
    num_part=counter_lbl.cget("text").split(":")[1].strip()
    counter_lbl.config(foreground="black")
    for part in counter_lbl.winfo_children():part.destroy()
    counter_lbl.config(text=f"Eingebucht: {session_count}")
    counter_lbl_color.itemconfig if False else None
    counter_lbl.tag_raise if False else None
    counter_lbl.configure(fg=color)

def handle_scan_or_enter(event=None):
    val=search_var.get().strip().replace(" ","")
    if not val:return
    if einbuchen_mode:
        if not active_zone:
            show_zone_warn();log("Zone auswählen!");search_var.set("");return
        hide_zone_warn()
        match_sn,match_name,near=best_directory_match(val)
        target_sn=match_sn if match_sn else val;target_name=match_name if match_sn else None
        if near and not match_sn:
            keep=sorted(near,key=lambda x:x[1],reverse=True)[0][0]
            row=c.execute("SELECT name FROM directory WHERE sendungsnr=?",(keep,)).fetchone()
            target_sn=keep;target_name=row[0] if row else None
        if near and (match_sn or len(near)>1):
            merge_near_packages(near,target_sn,target_name or "",active_zone)
        else:
            ts=datetime.now().isoformat(timespec="seconds")
            c.execute("REPLACE INTO packages(sendungsnr,zone,received_at,name) VALUES(?,?,?,?)",
                      (target_sn,active_zone,ts,target_name));conn.commit()
        inc_counter();log(f"{val} → {target_sn} ({target_name or '-'}) in {active_zone}")
        search_var.set("");run_search()
    else:run_search()
    app.after(10,keep_focus)

def keep_focus():search_entry.focus_set()

def inc_counter():
    global session_count;session_count+=1;update_counter_label()

def reset_counter():
    global session_count;session_count=0;update_counter_label()

def set_zone(z):
    global active_zone
    active_zone=z;hide_zone_warn()
    for n,b in zone_buttons.items():
        if n==z:b.config(bg=ARAL_BLUE,fg=WHITE,activebackground=ARAL_BLUE,activeforeground=WHITE)
        else:b.config(bg=WHITE,fg=ARAL_BLUE,activebackground=WHITE,activeforeground=ARAL_BLUE)
    zone_var.set(f"Aktive Zone: {active_zone}");search_entry.focus_set()

def toggle_einbuchen():
    global einbuchen_mode,active_zone
    einbuchen_mode=not einbuchen_mode
    if einbuchen_mode:
        einbuchen_btn.config(text="Fertig",bg=ARAL_RED,fg=WHITE)
        zone_var.set("Einbuchen aktiv – bitte Zone wählen")
        if not active_zone:show_zone_warn()
    else:
        einbuchen_btn.config(text="Einbuchen",bg=ARAL_BLUE,fg=WHITE)
        zone_var.set("Suche aktiv");hide_zone_warn();reset_counter();active_zone=None
    search_entry.focus_set()

def rfsearch(term,sn,nm,zn):return max(rf_score(term,sn),rf_score(term,nm or ""),rf_score(term,zn or ""))

def fetch_packages_all():
    rows=c.execute("""SELECT p.sendungsnr,COALESCE(p.name,d.name,''),COALESCE(p.zone,''),p.received_at
                      FROM packages p LEFT JOIN directory d ON d.sendungsnr=p.sendungsnr
                      ORDER BY p.received_at DESC""").fetchall();return rows

def run_search(event=None):
    term=search_var.get().strip();result_list.delete(0,tk.END)
    rows=fetch_packages_all()
    if not rows:result_list.insert(tk.END,"Keine Pakete");return
    if not term:
        for sn,nm,zn,ts in rows:result_list.insert(tk.END,f"{sn} — {nm or '-'} → {zn or '-'} ({ts})");return
    scored=[]
    for sn,nm,zn,ts in rows:
        sc=rfsearch(term,sn,nm,zn)
        if sc>=70:scored.append((sc,sn,nm,zn,ts))
    if not scored:result_list.insert(tk.END,"Kein Treffer");return
    scored.sort(key=lambda x:x[0],reverse=True)
    for sc,sn,nm,zn,ts in scored:result_list.insert(tk.END,f"{sn} — {nm or '-'} → {zn or '-'} ({ts})")

def delete_selected():
    sel=result_list.curselection()
    if not sel:return
    sn=result_list.get(sel[0]).split("—")[0].strip()
    c.execute("DELETE FROM packages WHERE sendungsnr=?",(sn,));conn.commit()
    result_list.delete(sel[0]);log(f"{sn} gelöscht")

app=ttk.Window(title="Paket-Zonen-Manager",themename="flatly")
app.geometry("1280x800+0+0")

zone_var=tk.StringVar(value="Suche aktiv");search_var=tk.StringVar()

top=ttk.Frame(app,padding=8);top.pack(fill=tk.X)
ttk.Label(top,textvariable=zone_var,font=("Roboto",22,"bold")).pack(side=tk.LEFT)
counter_lbl=ttk.Label(top,font=("Roboto",28,"bold"),foreground="black");counter_lbl.pack(side=tk.RIGHT)
session_count=0;update_counter_label()

search_row=ttk.Frame(app,padding=(12,6));search_row.pack(fill=tk.X)
ttk.Label(search_row,text="Eingabe (Name / Nummer):",font=("Roboto",18)).grid(row=0,column=0,sticky=tk.W,padx=(0,10))
search_entry=ttk.Entry(search_row,textvariable=search_var,font=("Consolas",26),width=22)
search_entry.grid(row=0,column=1,sticky=tk.W)
search_entry.bind("<Return>",handle_scan_or_enter)
search_entry.focus_set()

zones_frame=tk.Frame(app,bg=WHITE,padx=12,pady=8);zones_frame.pack(fill=tk.BOTH,expand=True)
grid=tk.Frame(zones_frame,bg=WHITE);grid.pack(expand=True,anchor="center",fill=tk.BOTH)
for col in range(5):grid.grid_columnconfigure(col,weight=(2 if col<=2 else 1))
for row in range(6):grid.grid_rowconfigure(row,weight=(0 if row==0 else 1))

def make_zone_btn(name,r,c,colspan=1,rowspan=1,font_size=44,pad=14,bg=WHITE,fg=ARAL_BLUE):
    btn=tk.Button(grid,text=name,command=lambda z=name:set_zone(z),
                  font=("Roboto",font_size,"bold"),bg=bg,fg=fg,
                  activebackground=bg,activeforeground=fg,relief="flat",borderwidth=0)
    btn.grid(row=r,column=c,columnspan=colspan,rowspan=rowspan,padx=pad,pady=pad,sticky="nsew")
    zone_buttons[name]=btn;return btn

ctrl=tk.Frame(grid,bg=WHITE);ctrl.grid(row=2,column=3,columnspan=2,sticky="nsew",padx=14,pady=(14,0))
einbuchen_btn=tk.Button(ctrl,text="Einbuchen",font=("Roboto",24,"bold"),
                        bg=ARAL_BLUE,fg=WHITE,activebackground=ARAL_BLUE,activeforeground=WHITE,
                        relief="flat",borderwidth=2,padx=24,pady=24,command=toggle_einbuchen)
einbuchen_btn.grid(row=0,column=0,sticky="nsew",ipadx=10,ipady=10)

make_zone_btn("A",1,0,colspan=3,font_size=48);make_zone_btn("B",2,0,colspan=3,font_size=48)
make_zone_btn("C",3,0,colspan=3,font_size=48);make_zone_btn("D",4,0,colspan=3,font_size=48)
make_zone_btn("E-1",5,0,font_size=40);make_zone_btn("E-2",5,1,font_size=40)
make_zone_btn("E-3",5,2,font_size=40);make_zone_btn("E-4",5,3,font_size=40);make_zone_btn("F",5,4,font_size=40)

warn_label=tk.Label(grid,text="Zone auswählen!",font=("Roboto",26,"bold"),bg=WHITE,fg=ARAL_RED)
warn_label.place_forget()

lists=ttk.Frame(app,padding=(12,6));lists.pack(fill=tk.BOTH,expand=True)
result_list=tk.Listbox(lists,font=("Consolas",18),height=7);result_list.pack(fill=tk.BOTH,expand=True,side=tk.LEFT,padx=(0,8))
log_list=tk.Listbox(lists,font=("Consolas",14),height=7);log_list.pack(fill=tk.BOTH,expand=True,side=tk.RIGHT)

actions=ttk.Frame(app,padding=(12,6));actions.pack(fill=tk.X)
ttk.Button(actions,text="Treffer löschen",bootstyle="danger",command=delete_selected).pack(side=tk.LEFT,padx=6,ipadx=16,ipady=10)

sync_directory();app.after(30000,periodic_sync);app.after(100,keep_focus)
run_search();app.mainloop()
