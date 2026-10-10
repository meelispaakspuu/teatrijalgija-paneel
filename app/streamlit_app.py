"""Teatrijälgija juhtpaneel (Streamlit Community Cloud).

Secrets (.streamlit/secrets.toml või Streamlit Cloudi "Secrets"):
    GH_TOKEN = "github_pat_..."   # fine-grained PAT: Contents RW + Actions RW, ainult see repo
    GH_REPO = "kasutaja/teatrijalgija"
    APP_PASSWORD = "..."          # valikuline
"""
from __future__ import annotations

import hmac
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import yaml

from github_store import GitHubStore
import ajakava as sched

TZ = ZoneInfo("Europe/Tallinn")
WD = {"mon": "E", "tue": "T", "wed": "K", "thu": "N", "fri": "R", "sat": "L", "sun": "P"}
WD_IDX = list(WD)
STATUS_ET = {"on_sale": "müügis", "sold_out": "välja müüdud", "not_started": "müük algamata",
             "paused": "peatatud"}
TABLE_ROWS = 20
TABLE_HEIGHT = 38 + 35 * TABLE_ROWS  # päis + 20 rida


def seats_text(x) -> str:
    """Kohtade arv tekstina; teadmata -> tühi (Streamlit näitaks muidu halli "None")."""
    return "" if x is None or (isinstance(x, float) and x != x) else str(int(x))


TYPE_ET = {"new_show": "uus etendus", "sale_scheduled": "müük algab", "sale_started": "müük avanes",
           "returned": "kohad vabanesid"}
NOTIFY_LABELS = {"new_show": "Uus etendus kohe müügis", "sale_scheduled": "Müük algab hiljem (piletikeskus)",
                 "sale_started": "Müük avanes / jätkus", "returned": "Väljamüüdud etendusele tekkisid kohad"}

st.set_page_config(page_title="Teatrijälgija", page_icon="🎭", layout="wide")


# ---------------------------------------------------------------- auth & data

def check_password() -> bool:
    pw = st.secrets.get("APP_PASSWORD")
    if not pw or st.session_state.get("auth"):
        return True
    given = st.text_input("Parool", type="password")
    if given and hmac.compare_digest(given, pw):
        st.session_state.auth = True
        st.rerun()
    elif given:
        st.error("Vale parool")
    return False


if not check_password():
    st.stop()


@st.cache_resource
def _store(token: str, repo: str, code_version: str) -> GitHubStore:
    return GitHubStore(token, repo)


def store() -> GitHubStore:
    # code_version: kui github_store.py muutub, luuakse uus objekt (vana jääks muidu vahemällu)
    import hashlib
    import github_store as _gs
    ver = hashlib.sha1(open(_gs.__file__, "rb").read()).hexdigest()[:12]
    return _store(st.secrets["GH_TOKEN"], st.secrets["GH_REPO"], ver)


@st.cache_data(ttl=60, show_spinner=False)
def load_state() -> dict:
    return store().read_json("state.json")


def load_config() -> tuple[dict, str | None]:
    text, sha = store().read("config.yaml")
    return (yaml.safe_load(text) or {}) if text else {}, sha


def save_config(cfg: dict, msg: str) -> None:
    text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False)
    st.session_state.cfg_sha = store().write("config.yaml", text, st.session_state.cfg_sha, msg)
    st.session_state.cfg = cfg
    st.toast(f"Salvestatud: {msg}", icon="✅")


if "cfg" not in st.session_state:
    st.session_state.cfg, st.session_state.cfg_sha = load_config()
cfg: dict = st.session_state.cfg
state = load_state()


def fmt_local(iso: str | None, with_date=True) -> str:
    if not iso:
        return "—"
    d = datetime.fromisoformat(iso).astimezone(TZ)
    return d.strftime("%d.%m %H:%M" if with_date else "%H:%M")


# ---------------------------------------------------------------- header

st.title("🎭 Teatrijälgija")
c1, c2, c3, c4 = st.columns([2, 2, 1.3, 1.3])
c1.metric("Viimane kontroll", fmt_local(state.get("last_run")))
paused = [r["name"] for r in cfg.get("recipients", []) if r.get("pause_until")
          and str(r["pause_until"]) >= date.today().isoformat()]
c2.metric("Paus", ", ".join(paused) if paused else "ei")
if c3.button("🔄 Kontrolli kohe", width="stretch"):
    store().dispatch(manual=True)
    st.success("Käivitatud. Tulemus on ~1 minuti pärast vahelehel „Tervis“ (vajuta „Värskenda andmeid“). "
               "Telefoni tuleb teade ainult siis, kui midagi muutus.")
if c4.button("🔔 Testteade", width="stretch"):
    store().dispatch(manual=False, test_notify=True)
    st.success("Testteade teele saadetud.")

tab_shows, tab_log, tab_settings, tab_theatres, tab_health = st.tabs(
    ["Etendused", "Teated", "Seaded", "Teatrid", "Tervis"])

# ---------------------------------------------------------------- etendused

with tab_shows:
    rows = []
    for v in (state.get("shows") or {}).values():
        rows.append({"Teater": v.get("theatre_name"), "Lavastus": v["title"],
                     "Aeg": datetime.fromisoformat(v["start"]).astimezone(TZ).replace(tzinfo=None),
                     "Saal": v.get("venue"), "Staatus": STATUS_ET.get(v["status"], v["status"]),
                     "Kohti": v.get("seats"), "Allikas": v["source"], "Link": v.get("url")})
    if not rows:
        st.info("Andmeid veel pole. Vajuta „Kontrolli kohe“ või oota esimest ajastatud jooksu.")
    else:
        df = pd.DataFrame(rows).sort_values("Aeg")
        df["Kohti"] = df["Kohti"].map(seats_text)
        f1, f2, f3 = st.columns([2, 2, 2])
        th = f1.multiselect("Teater", sorted(df["Teater"].dropna().unique()))
        stt = f2.multiselect("Staatus", list(STATUS_ET.values()))
        q = f3.text_input("Otsi lavastust")
        if th:
            df = df[df["Teater"].isin(th)]
        if stt:
            df = df[df["Staatus"].isin(stt)]
        if q:
            df = df[df["Lavastus"].str.contains(q, case=False, na=False)]
        st.caption(f"{len(df)} etendust")
        st.dataframe(df, hide_index=True, width="stretch", height=TABLE_HEIGHT, column_config={
            "Aeg": st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm"),  # moment.js: DD = päev, dd = nädalapäev
            "Link": st.column_config.LinkColumn(display_text="ava")})

# ---------------------------------------------------------------- teated

with tab_log:
    log = list(reversed(state.get("log") or []))
    if not log:
        st.info("Teateid pole veel saadetud.")
    else:
        log_df = pd.DataFrame([{
            "Millal": fmt_local(e["time"]), "Kellele": e.get("recipient"),
            "Tüüp": TYPE_ET.get(e["type"], e["type"]), "Teater": e.get("theatre_name"),
            "Lavastus": e.get("title"), "Etendus": fmt_local(e.get("start")),
            "Kohti": e.get("seats"), "Tulemus": e.get("delivered"), "Link": e.get("url")} for e in log])
        log_df["Kohti"] = log_df["Kohti"].map(seats_text)
        st.dataframe(log_df,
            hide_index=True, width="stretch", height=TABLE_HEIGHT,
            column_config={"Link": st.column_config.LinkColumn(display_text="ava")})

# ---------------------------------------------------------------- seaded

with tab_settings:
    with st.expander("⏱ Kontrollimise sagedus", expanded=False):
        st.caption("Teated tulevad ainult muudatuste korral. Siin määrad, kui tihti jälgija lehti kontrollib. "
                   "Ajakava muudetakse GitHubi workflow-failis; muudatus hakkab kehtima mõne minuti jooksul.")
        sset = cfg.setdefault("settings", {})
        sc = sset.get("schedule") or {"interval_min": 30, "start_h": 8, "end_h": 24, "night_checks": True}
        with st.container(border=True):
            iv = st.select_slider("Kontrolli iga", key="sched_iv", options=sched.INTERVALS, value=int(sc.get("interval_min", 30)),
                                  format_func=lambda m: f"{m} min" if m < 60 else f"{m // 60} h")
            h1, h2 = st.columns(2)
            sh = h1.number_input("Esimene kontroll (kell)", 0, 22, int(sc.get("start_h", 8)))
            eh = h2.number_input(f"Viimane kontroll enne (kell, max {sched.LATEST_HOUR})", 1, sched.LATEST_HOUR,
                                 min(int(sc.get("end_h", sched.LATEST_HOUR)), sched.LATEST_HOUR))
            night = st.checkbox("Öösel lisaks 2 kontrolli (kell 3 ja 6)", value=bool(sc.get("night_checks", True)))
            crons = sched.build_crons(int(iv), int(sh), int(eh), night)
            mins = sched.monthly_minutes(crons)
            pct = mins / sched.FREE_MINUTES
            last = sched.last_check_local(int(iv), int(sh), int(eh))
            st.markdown(f"**{sched.runs_per_day(crons)} kontrolli päevas**, viimane kell **{last}** · "
                        f"hinnanguliselt **~{mins} Actionsi minutit kuus** ({pct:.0%} tasuta limiidist "
                        f"{sched.FREE_MINUTES} min)")
            too_much = pct > 1.0
            if too_much:
                st.error("See ületab tasuta limiidi. Lühenda päevast ajavahemikku, lülita öised kontrollid välja "
                         "või vali pikem intervall.")
            elif pct > 0.85:
                st.warning("Limiidi lähedal: kui mõni jooks võtab üle 1 minuti, arvestatakse 2 minutit. "
                           "Limiidi ületamisel peatab GitHub jooksud kuu lõpuni.")
            if st.button("💾 Salvesta ajakava", type="primary", disabled=too_much, key="save_schedule"):
                try:
                    wf_path = ".github/workflows/watch.yml"
                    wf_text, wf_sha = store().read(wf_path, branch="main")
                    new_wf = sched.replace_block(wf_text, crons)
                    if new_wf != wf_text:
                        store().write(wf_path, new_wf, wf_sha, f"Ajakava: iga {iv} min", branch="main")
                    sset["schedule"] = {"interval_min": int(iv), "start_h": int(sh), "end_h": int(eh),
                                        "night_checks": bool(night)}
                    save_config(cfg, f"ajakava iga {iv} min")
                except PermissionError as exc:
                    st.error(str(exc))
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Ajakava salvestamine ebaõnnestus: {exc}")
        try:
            wf_now, _ = store().read(".github/workflows/watch.yml", branch="main")
            st.caption("Praegune ajakava (UTC): " + " · ".join(f"`{c}`" for c in sched.current_crons(wf_now or "")))
        except Exception:  # noqa: BLE001
            pass

    with st.expander("📊 Olekuteated (süsteemisaajatele)", expanded=False):
        st.caption("Olekuteade näitab, kas kõik allikad töötavad ja mitu kontrolli on vahepeal tehtud. "
                   "Sisulised teated (piletid, uued etendused) ja tõrketeated tulevad sellest sõltumata. "
                   "Vaiksel ajal olekuteateid ei saadeta.")
        sset = cfg.setdefault("settings", {})
        cur = dict(sset.get("status_report") or {})
        cur.setdefault("mode", "weekly")
        modes = {"run": "Iga kontrolli järel (ainult testimiseks)", "hours": "Iga N tunni järel",
                 "daily": "Kord päevas", "weekly": "Kord nädalas", "off": "Ei saada"}
        with st.container(border=True):
            mode = st.radio("Sagedus", list(modes), index=list(modes).index(cur["mode"]),
                            format_func=modes.get, key="sr_mode")
            new = {"mode": mode}
            if mode == "hours":
                new["hours"] = st.select_slider("Iga", options=[1, 2, 3, 4, 6, 8, 12],
                                                value=int(cur.get("hours", 6)), format_func=lambda h: f"{h} h",
                                                key="sr_hours")
            if mode in ("daily", "weekly"):
                c1, c2 = st.columns(2)
                if mode == "weekly":
                    new["weekday"] = c1.selectbox("Päev", list(range(7)), index=int(cur.get("weekday", 0)),
                                                  format_func=lambda d: ["esmaspäev", "teisipäev", "kolmapäev",
                                                                         "neljapäev", "reede", "laupäev",
                                                                         "pühapäev"][d], key="sr_wd")
                new["hour"] = c2.number_input("Alates kell", 0, 23, int(cur.get("hour", 9)), key="sr_hour")
                st.caption("Saadetakse esimesel kontrollil pärast seda kellaaega.")
            if st.button("💾 Salvesta olekuteadete sagedus", key="sr_save"):
                sset["status_report"] = new
                save_config(cfg, f"olekuteated: {modes[mode].lower()}")

    theatres = cfg.get("theatres") or {}
    th_ids = list(theatres)
    recipients = cfg.setdefault("recipients", [])
    for i, r in enumerate(recipients):
        is_open = r["name"] == st.session_state.get("open_rcp") or (i == 0 and "open_rcp" not in st.session_state)
        with st.expander(f"👤 {r['name']}" + ("  · süsteemiteated" if r.get("system") else ""), expanded=is_open):
            # Paus: üks puudutus telefonist
            st.markdown("**Paus**")
            p1, p2, p3, p4 = st.columns(4)
            for col, weeks in ((p1, 1), (p2, 2), (p3, 4)):
                if col.button(f"{weeks} näd", key=f"p{weeks}_{i}", width="stretch"):
                    r["pause_until"] = (date.today() + timedelta(weeks=weeks)).isoformat()
                    save_config(cfg, f"{r['name']}: paus kuni {r['pause_until']}")
            if p4.button("▶️ Jätka", key=f"resume_{i}", width="stretch"):
                r["pause_until"] = None
                save_config(cfg, f"{r['name']}: paus lõpetatud")
            if r.get("pause_until"):
                st.caption(f"Paus kuni {r['pause_until']} (k.a)")

            with st.form(f"rcp_{i}"):
                cur_pause = date.fromisoformat(str(r["pause_until"])[:10]) if r.get("pause_until") else None
                if cur_pause and cur_pause < date.today():
                    cur_pause = None  # aegunud paus
                pause_d = st.date_input("…või paus kuni kuupäevani", value=cur_pause,
                                        min_value=date.today(), format="DD.MM.YYYY")
                qh = r.get("quiet_hours") or ""
                q_on = st.toggle("Vaikne aeg (teated kogutakse ja saadetakse hommikul)", value=bool(qh))
                qa, qb = (qh.split("-") if qh else ("22:00", "08:00"))
                t1, t2 = st.columns(2)
                q_from = t1.time_input("Alates", value=time.fromisoformat(qa.strip()), step=1800)
                q_to = t2.time_input("Kuni", value=time.fromisoformat(qb.strip()), step=1800)
                sel_th = st.multiselect("Teatrid (tühi = kõik)", th_ids, default=[t for t in r.get("theatres") or [] if t in th_ids],
                                        format_func=lambda t: theatres[t].get("name", t))
                wd = st.multiselect("Nädalapäevad (tühi = kõik)", WD_IDX, default=r.get("weekdays") or [],
                                    format_func=WD.get)
                a1, a2 = st.columns(2)
                horizon = a1.slider("Mitu päeva ette", 7, 365, int(r.get("max_days_ahead") or 120), step=7)
                min_seats = a2.number_input("Vähemalt kohti", 1, 10, int(r.get("min_seats") or 1))
                is_sys = st.toggle("Süsteemiteated (allikate tõrked + nädalaülevaade esmaspäeval kell 9)",
                                   value=bool(r.get("system", i == 0)), key=f"sys_{i}")
                st.markdown("**Teavituse tüübid**")
                n = r.get("notify") or {}
                new_notify = {k: st.checkbox(lbl, value=n.get(k, True), key=f"n_{k}_{i}")
                              for k, lbl in NOTIFY_LABELS.items()}
                watch = st.text_area("Ainult need lavastused (üks rea kohta, osa pealkirjast; tühi = kõik)",
                                     "\n".join(r.get("watch") or []))
                ignore = st.text_area("Ignoreeri (üks rea kohta)", "\n".join(r.get("ignore") or []))
                topic = st.text_input("ntfy teema", r.get("topic", ""), type="password")
                if st.form_submit_button("💾 Salvesta", type="primary"):
                    r.update(
                        pause_until=pause_d.isoformat() if pause_d else None,
                        quiet_hours=f"{q_from:%H:%M}-{q_to:%H:%M}" if q_on else None,
                        theatres=sel_th, weekdays=wd, max_days_ahead=horizon, min_seats=int(min_seats),
                        notify=new_notify,
                        watch=[x.strip() for x in watch.splitlines() if x.strip()],
                        ignore=[x.strip() for x in ignore.splitlines() if x.strip()],
                        topic=topic.strip(), system=bool(is_sys))
                    save_config(cfg, f"{r['name']}: seaded")
            st.caption(f"Telefonis: ntfy äpp → + → teema nimi. Veebis: https://ntfy.sh/{r.get('topic', '')}")
            if len(recipients) > 1:
                d1, d2 = st.columns([3, 1])
                sure = d1.checkbox(f"Kinnitan, et eemaldan saaja {r['name']}", key=f"delok_{i}")
                if d2.button("🗑 Eemalda", key=f"del_{i}", disabled=not sure, width="stretch"):
                    removed = recipients.pop(i)
                    save_config(cfg, f"eemaldatud saaja {removed['name']}")
                    st.session_state.pop("open_rcp", None)
                    st.session_state.pop("added_rcp", None)
                    st.rerun()

    if st.session_state.get("added_rcp"):
        nm_, tp_ = st.session_state["added_rcp"]
        st.success(f"Saaja **{nm_}** lisatud. Tema telefonis: ntfy äpp → **+** → teema nimi "
                   f"**`{tp_}`** → Subscribe. Filtreid saad muuta tema plokis ülal.")
    with st.expander("➕ Lisa saaja"):
        import secrets as _secrets
        if "new_topic" not in st.session_state:
            st.session_state.new_topic = "teater-" + _secrets.token_urlsafe(16).replace("_", "x").replace("-", "y")
        with st.form("add_rcp"):
            nm = st.text_input("Nimi")
            new_th = st.multiselect("Teatrid (tühi = kõik)", th_ids, format_func=lambda t: theatres[t].get("name", t))
            new_wd = st.multiselect("Nädalapäevad (tühi = kõik)", WD_IDX, format_func=WD.get)
            new_min = st.number_input("Vähemalt kohti", 1, 10, 1)
            tp = st.text_input("ntfy teema (genereeritud, võid jätta nii)", st.session_state.new_topic)
            st.caption("Ülejäänud seaded (vaikne aeg, lavastuste filter, teavituse tüübid, paus) saad muuta "
                       "pärast lisamist saaja plokis.")
            if st.form_submit_button("Lisa", type="primary"):
                if not nm.strip():
                    st.error("Sisesta nimi.")
                elif any(r["name"] == nm.strip() for r in recipients):
                    st.error("Sellise nimega saaja on juba olemas.")
                elif len(tp.strip()) < 16:
                    st.error("ntfy teema peab olema vähemalt 16 märki (see on ainus kaitse võõraste eest).")
                else:
                    recipients.append({"name": nm.strip(), "topic": tp.strip(), "system": False,
                                       "theatres": new_th, "quiet_hours": "22:00-08:00", "pause_until": None,
                                       "weekdays": new_wd, "max_days_ahead": 120, "min_seats": int(new_min),
                                       "notify": {k: True for k in NOTIFY_LABELS}, "watch": [], "ignore": []})
                    save_config(cfg, f"lisatud saaja {nm.strip()}")
                    st.session_state.open_rcp = nm.strip()
                    st.session_state.added_rcp = (nm.strip(), tp.strip())
                    del st.session_state["new_topic"]
                    st.rerun()

# ---------------------------------------------------------------- teatrid

with tab_theatres:
    with st.form("theatres"):
        for tid, t in theatres.items():
            st.markdown(f"**{t.get('name', tid)}**")
            t["enabled"] = st.toggle("Jälgi", value=t.get("enabled", True), key=f"te_{tid}")
            for j, s in enumerate(t.get("sources") or []):
                s["enabled"] = st.checkbox(f"{s['type']} · {s['org']}", value=s.get("enabled", True),
                                           key=f"se_{tid}_{j}")
            st.divider()
        if st.form_submit_button("💾 Salvesta teatrid", type="primary"):
            save_config(cfg, "teatrid")

# ---------------------------------------------------------------- tervis

with tab_health:
    h = state.get("health") or {}
    if h:
        st.dataframe(pd.DataFrame([{
            "Allikas": k, "Korras": "✅" if v.get("ok") else "❌", "Etendusi": v.get("count"),
            "Lehti": v.get("pages"), "Viimati korras": fmt_local(v.get("last_ok")),
            "Hoiatus": v.get("warning") or "", "Viga": v.get("error") or ""} for k, v in h.items()]),
            hide_index=True, width="stretch")
    st.markdown("**Viimased jooksud**")
    try:
        runs = store().runs()
        st.dataframe(pd.DataFrame([{
            "Algus": fmt_local(r["run_started_at"].replace("Z", "+00:00")), "Käivitaja": r["event"],
            "Tulemus": r.get("conclusion") or r["status"], "Logi": r["html_url"]} for r in runs]),
            hide_index=True, width="stretch",
            column_config={"Logi": st.column_config.LinkColumn(display_text="ava")})
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Jooksude nimekirja ei saanud lugeda: {exc}")
    with st.expander("Viimase jooksu statistika"):
        st.code(json.dumps(state.get("last_run_stats") or {}, ensure_ascii=False, indent=1), language="json")

if st.button("↻ Värskenda andmeid"):
    load_state.clear()
    st.session_state.cfg, st.session_state.cfg_sha = load_config()
    st.rerun()
