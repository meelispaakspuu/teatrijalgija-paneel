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

TZ = ZoneInfo("Europe/Tallinn")
WD = {"mon": "E", "tue": "T", "wed": "K", "thu": "N", "fri": "R", "sat": "L", "sun": "P"}
WD_IDX = list(WD)
STATUS_ET = {"on_sale": "müügis", "sold_out": "välja müüdud", "not_started": "müük algamata",
             "paused": "peatatud"}
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
def store() -> GitHubStore:
    return GitHubStore(st.secrets["GH_TOKEN"], st.secrets["GH_REPO"])


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
    st.success("Käivitatud. Tulemus tuleb telefoni ~1–2 minuti pärast.")
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
        st.dataframe(df, hide_index=True, width="stretch", column_config={
            "Aeg": st.column_config.DatetimeColumn(format="dd.MM.YYYY HH:mm"),
            "Link": st.column_config.LinkColumn(display_text="ava"),
            "Kohti": st.column_config.NumberColumn(format="%d")})

# ---------------------------------------------------------------- teated

with tab_log:
    log = list(reversed(state.get("log") or []))
    if not log:
        st.info("Teateid pole veel saadetud.")
    else:
        st.dataframe(pd.DataFrame([{
            "Millal": fmt_local(e["time"]), "Kellele": e.get("recipient"),
            "Tüüp": TYPE_ET.get(e["type"], e["type"]), "Teater": e.get("theatre_name"),
            "Lavastus": e.get("title"), "Etendus": fmt_local(e.get("start")),
            "Kohti": e.get("seats"), "Tulemus": e.get("delivered"), "Link": e.get("url")} for e in log]),
            hide_index=True, width="stretch",
            column_config={"Link": st.column_config.LinkColumn(display_text="ava")})

# ---------------------------------------------------------------- seaded

with tab_settings:
    theatres = cfg.get("theatres") or {}
    th_ids = list(theatres)
    recipients = cfg.setdefault("recipients", [])
    for i, r in enumerate(recipients):
        with st.expander(f"👤 {r['name']}", expanded=(i == 0)):
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
                        topic=topic.strip())
                    save_config(cfg, f"{r['name']}: seaded")
            st.caption(f"Telefonis: ntfy äpp → + → teema nimi. Veebis: https://ntfy.sh/{r.get('topic', '')}")

    with st.expander("➕ Lisa saaja"):
        with st.form("add_rcp"):
            nm = st.text_input("Nimi")
            tp = st.text_input("ntfy teema (pikk juhuslik nimi)")
            if st.form_submit_button("Lisa") and nm and tp:
                recipients.append({"name": nm, "topic": tp, "theatres": [], "quiet_hours": "22:00-08:00",
                                   "pause_until": None, "weekdays": [], "max_days_ahead": 120,
                                   "min_seats": 1, "notify": {k: True for k in NOTIFY_LABELS},
                                   "watch": [], "ignore": []})
                save_config(cfg, f"lisatud saaja {nm}")
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
