# app.py
import streamlit as st
from supabase import create_client
from datetime import date
import math

st.set_page_config(page_title="Baseball Game Tracker", layout="wide")

# ---------------------------
#  Supabase connection
# ---------------------------
try:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
except Exception:
    st.error("Supabase secrets missing. Add [supabase] url and key to Streamlit secrets.")
    st.stop()

supabase = create_client(url, key)

# ---------------------------
#  Utilities
# ---------------------------
def ensure_player(name, team=None, throws=None, bats=None):
    """Return PlayerID for name (create if missing)."""
    if not name or str(name).strip() == "":
        return None
    r = supabase.table("Players").select("PlayerID").eq("Name", name).execute()
    if r.data:
        return r.data[0]["PlayerID"]
    payload = {"Name": name}
    if team is not None:
        payload["Team"] = team
    if throws is not None:
        payload["Throws"] = throws
    if bats is not None:
        payload["Bats"] = bats
    created = supabase.table("Players").insert(payload).execute()
    return created.data[0]["PlayerID"] if created.data else None

def create_game(home, away, gamedate):
    r = supabase.table("Games").insert({
        "HomeTeam": home,
        "AwayTeam": away,
        "GameDate": str(gamedate)
    }).execute()
    return r.data[0]["GameID"] if r.data else None

def create_atbat(game_id, batter_id, pitcher_id, inning, order=None, leadoff=None, leadoff_on=None, play_result=None, runs_scored=0, earned_runs=0, korbb=None):
    payload = {
        "GameID": int(game_id),
        "BatterID": int(batter_id),
        "PitcherID": int(pitcher_id),
        "Inning": int(inning),
        "RunsScored": int(runs_scored),
        "EarnedRuns": int(earned_runs)
    }
    if order is not None:
        payload["BatterOrder"] = int(order)
    if leadoff is not None:
        payload["LeadOff"] = bool(leadoff)
    if leadoff_on is not None:
        payload["LeadOffOn"] = bool(leadoff_on)
    if play_result:
        payload["PlayResult"] = play_result
    if korbb:
        payload["KorBB"] = korbb
    resp = supabase.table("AtBats").insert(payload).execute()
    return resp.data[0]["AtBatID"] if resp.data else None

def next_pitch_numbers_for(atbat_id):
    """Return (next global PitchNo, next PitchOfAB)"""
    # global max PitchNo
    rg = supabase.table("Pitches").select("PitchNo").order("PitchNo", desc=True).limit(1).execute()
    last_global = rg.data[0]["PitchNo"] if rg.data else 0
    # per atbat count
    ra = supabase.table("Pitches").select("PitchOfAB").eq("AtBatID", atbat_id).order("PitchOfAB", desc=True).limit(1).execute()
    last_poab = ra.data[0]["PitchOfAB"] if ra.data else 0
    return last_global + 1, last_poab + 1

def compute_wel(balls, strikes):
    """W/E/L rule from coach: Early if (0-0,0-1,1-0,1-1), Win if (0-2,1-2), Lose if (2-0,2-1)"""
    t = (balls, strikes)
    if t in [(0,0),(0,1),(1,0),(1,1)]:
        return "E"
    if t in [(0,2),(1,2)]:
        return "W"
    if t in [(2,0),(2,1)]:
        return "L"
    return None

def delete_last_pitch(pitch_id):
    supabase.table("Pitches").delete().eq("PitchID", pitch_id).execute()

def safe_float(x):
    try:
        if x is None:
            return None
        if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
            return None
        return float(x)
    except Exception:
        return None

# ---------------------------
#  Session state defaults
# ---------------------------
if "lineup" not in st.session_state:
    st.session_state["lineup"] = []  # list of dicts {Name, Team, Bats, Order, PlayerID}
if "pitchers" not in st.session_state:
    st.session_state["pitchers"] = [] # list of dicts {Name, Team, Throws, PlayerID}
if "selected_game_id" not in st.session_state:
    st.session_state["selected_game_id"] = None
if "current_atbat_id" not in st.session_state:
    st.session_state["current_atbat_id"] = None
if "current_batter_id" not in st.session_state:
    st.session_state["current_batter_id"] = None
if "current_pitcher_id" not in st.session_state:
    st.session_state["current_pitcher_id"] = None
if "balls" not in st.session_state:
    st.session_state["balls"] = 0
if "strikes" not in st.session_state:
    st.session_state["strikes"] = 0
if "pitch_history" not in st.session_state:
    st.session_state["pitch_history"] = []  # stack of pitchIDs
if "last_pitch_summary" not in st.session_state:
    st.session_state["last_pitch_summary"] = None
if "last_saved_pitch_id" not in st.session_state:
    st.session_state["last_saved_pitch_id"] = None

# ---------------------------
#  UI: Header
# ---------------------------
st.title("⚾ Baseball Game Tracker")
st.caption("Set lineup and pitchers in Setup. Use quick buttons for realtime entry and manual form for detail.")

# ---------------------------
#  1) Game Setup & Lineup
# ---------------------------
with st.expander("1 — Game Setup & Lineup", expanded=True):
    col1, col2, col3 = st.columns([3,3,2])
    with col1:
        games = supabase.table("Games").select("GameID, GameDate, HomeTeam, AwayTeam").order("GameDate", desc=True).execute().data or []
        game_map = {f"{g['GameDate']} - {g['HomeTeam']} vs {g['AwayTeam']}": g["GameID"] for g in games}
        sel = st.selectbox("Select Game", ["-- Add New Game --"] + list(game_map.keys()))
        if sel == "-- Add New Game --":
            gh = st.text_input("Home Team")
            ga = st.text_input("Away Team")
            gd = st.date_input("Game Date", value=date.today())
            if st.button("Create Game"):
                gid = create_game(gh, ga, gd)
                if gid:
                    st.success("Game created. Select it from dropdown.")
                    st.rerun()
                else:
                    st.error("Failed creating game.")
            st.stop()
        else:
            st.session_state["selected_game_id"] = game_map[sel]
            st.write("Selected:", sel)

    with col2:
        st.subheader("Starting lineup (add hitters)")
        new_name = st.text_input("Hitter name", key="setup_hitter_name")
        new_bats = st.selectbox("Bats", ["Right","Left","Switch"], key="setup_hitter_bats")
        new_slot = st.number_input("Lineup slot", min_value=1, max_value=99, value=len(st.session_state["lineup"])+1, key="setup_hitter_slot")
        if st.button("Add Hitter to lineup"):
            if not new_name:
                st.warning("Enter a name.")
            else:
                pid = ensure_player(new_name, bats=new_bats)
                st.session_state["lineup"].append({"Name": new_name, "Team": None, "Bats": new_bats, "Order": int(new_slot), "PlayerID": pid})
                st.session_state["lineup"] = sorted(st.session_state["lineup"], key=lambda x: x["Order"])
                st.success(f"Added {new_name}")
                st.rerun()
        # Show lineup
        if st.session_state["lineup"]:
            st.write("Lineup (click Remove to delete entry):")
            for i, p in enumerate(st.session_state["lineup"]):
                cols = st.columns([4,1,1])
                cols[0].write(f"{p['Order']}. {p['Name']} ({p['Bats']})")
                if cols[2].button(f"RemoveHitter-{i}"):
                    st.session_state["lineup"].pop(i)
                    st.success("Removed.")
                    st.rerun()

    with col3:
        st.subheader("Pitchers")
        np_name = st.text_input("Pitcher name", key="setup_pitcher_name")
        np_throws = st.selectbox("Throws", ["Right","Left"], key="setup_pitcher_throws")
        if st.button("Add Pitcher"):
            if not np_name:
                st.warning("Enter pitcher name.")
            else:
                pid = ensure_player(np_name, throws=np_throws)
                st.session_state["pitchers"].append({"Name": np_name, "Team": None, "Throws": np_throws, "PlayerID": pid})
                st.success(f"Added pitcher {np_name}")
                st.rerun()
        if st.session_state["pitchers"]:
            st.write("Pitchers:")
            for j, q in enumerate(st.session_state["pitchers"]):
                cols = st.columns([4,1])
                cols[0].write(f"{q['Name']} ({q['Throws']})")
                if cols[1].button(f"RemPitch-{j}"):
                    st.session_state["pitchers"].pop(j)
                    st.success("Removed pitcher.")
                    st.rerun()

# ---------------------------
#  2) Select AtBat / Batter / Pitcher
# ---------------------------
st.header("2 — Select AtBat (choose batter and pitcher)")

col_b1, col_b2, col_b3 = st.columns([3,3,2])
with col_b1:
    # Batter dropdown populated from lineup with Add Batter option
    lineup_names = [p["Name"] for p in st.session_state["lineup"]]
    batter_choice = st.selectbox("Batter (choose from lineup or Add Batter)", ["-- Select --", "-- Add Batter --"] + lineup_names, key="batter_choice")
    if batter_choice == "-- Add Batter --":
        ab_name = st.text_input("New Batter Name", key="addbat_name")
        ab_bats = st.selectbox("Bats", ["Right","Left","Switch"], key="addbat_bats")
        ab_slot = st.number_input("Lineup slot", min_value=1, max_value=99, value=len(st.session_state["lineup"])+1, key="addbat_slot")
        if st.button("Add batter to lineup"):
            if not ab_name:
                st.warning("Enter a name.")
            else:
                pid = ensure_player(ab_name, bats=ab_bats)
                st.session_state["lineup"].append({"Name": ab_name, "Team": None, "Bats": ab_bats, "Order": int(ab_slot), "PlayerID": pid})
                st.session_state["lineup"] = sorted(st.session_state["lineup"], key=lambda x: x["Order"])
                st.success("Added batter.")
                st.rerun()
    elif batter_choice not in ["-- Select --", "-- Add Batter --"]:
        sel_batter = next((x for x in st.session_state["lineup"] if x["Name"] == batter_choice), None)
        if sel_batter:
            st.write(f"Selected batter: {sel_batter['Name']} (slot {sel_batter['Order']})")
            st.session_state["current_batter_id"] = sel_batter["PlayerID"]

with col_b2:
    # Pitcher selection
    pitcher_names = [p["Name"] for p in st.session_state["pitchers"]]
    pitcher_choice = st.selectbox("Pitcher (choose or Add Pitcher)", ["-- Select --", "-- Add Pitcher --"] + pitcher_names, key="pitch_choice")
    if pitcher_choice == "-- Add Pitcher --":
        ap_name = st.text_input("New Pitcher Name", key="add_pitch_name")
        ap_throws = st.selectbox("Throws", ["Right","Left"], key="add_pitch_throws")
        if st.button("Add pitcher & use"):
            if not ap_name:
                st.warning("Enter name.")
            else:
                pid = ensure_player(ap_name, throws=ap_throws)
                st.session_state["pitchers"].append({"Name": ap_name, "Team": None, "Throws": ap_throws, "PlayerID": pid})
                st.session_state["current_pitcher_id"] = pid
                st.success("Added pitcher.")
                st.rerun()
    elif pitcher_choice not in ["-- Select --", "-- Add Pitcher --"]:
        sel_pitch = next((x for x in st.session_state["pitchers"] if x["Name"] == pitcher_choice), None)
        if sel_pitch:
            st.write(f"Selected pitcher: {sel_pitch['Name']}")
            st.session_state["current_pitcher_id"] = sel_pitch["PlayerID"]

with col_b3:
    inning_val = st.number_input("Inning", min_value=1, value=1)
    # Start AtBat button only shows when both batter & pitcher selected
    if st.button("Start AtBat") and st.session_state["current_batter_id"] and st.session_state["current_pitcher_id"]:
        atbat_id = create_atbat(st.session_state["selected_game_id"], st.session_state["current_batter_id"], st.session_state["current_pitcher_id"], inning_val)
        if atbat_id:
            st.session_state["current_atbat_id"] = atbat_id
            st.session_state["balls"] = 0
            st.session_state["strikes"] = 0
            st.session_state["pitch_history"] = []
            st.session_state["last_pitch_summary"] = None
            st.session_state["last_saved_pitch_id"] = None
            st.success(f"AtBat {atbat_id} created.")
            st.rerun()
        else:
            st.error("Failed to create AtBat. Check DB constraints.")

# ---------------------------
#  3) Pitch Entry
# ---------------------------
st.header("3 — Pitch Entry (Realtime)")

if not st.session_state["current_atbat_id"]:
    st.info("Start an AtBat (choose batter & pitcher then Start AtBat).")
else:
    atbat_id = st.session_state["current_atbat_id"]

    # compute next pitch numbers
    pno, poab = next_pitch_numbers_for(atbat_id)
    st.write(f"Next PitchNo: **{pno}** — PitchOfAB: **{poab}**")
    st.write(f"Count: **{st.session_state['balls']}-{st.session_state['strikes']}**")

    # last pitch summary + undo
    if st.session_state["last_pitch_summary"]:
        st.info("Last pitch: " + st.session_state["last_pitch_summary"])
        if st.button("Undo Last Pitch"):
            if st.session_state["pitch_history"]:
                last = st.session_state["pitch_history"].pop()
                try:
                    delete_last_pitch(last)
                    # recompute count from DB
                    rem = supabase.table("Pitches").select("Balls,Strikes").eq("AtBatID", atbat_id).order("PitchOfAB", asc=True).execute().data or []
                    if rem:
                        st.session_state["balls"] = rem[-1].get("Balls", 0)
                        st.session_state["strikes"] = rem[-1].get("Strikes", 0)
                    else:
                        st.session_state["balls"] = 0
                        st.session_state["strikes"] = 0
                    st.session_state["last_pitch_summary"] = None
                    st.success("Undo successful.")
                    st.rerun()
                except Exception as e:
                    st.error("Undo failed: " + str(e))
            else:
                st.warning("No pitch to undo.")

    st.markdown("**Quick Buttons** — fastest for realtime")
    c1,c2,c3 = st.columns(3)
    with c1:
        if st.button("Ball Called"):
            st.session_state["balls"] = min(4, st.session_state["balls"] + 1)
            pitch_called = "Ball Called"
            resp = supabase.table("Pitches").insert({
                "AtBatID": atbat_id,
                "PitchNo": pno,
                "PitchOfAB": poab,
                "PitchType": None,
                "Velocity": None,
                "Zone": None,
                "PitchCalled": pitch_called,
                "WEL": compute_wel(st.session_state["balls"], st.session_state["strikes"]),
                "Balls": st.session_state["balls"],
                "Strikes": st.session_state["strikes"],
                "TaggedHit": None,
                "HitDirection": None,
                "KPI": None
            }).execute()
            if resp.data:
                st.session_state["pitch_history"].append(resp.data[0]["PitchID"])
                st.session_state["last_saved_pitch_id"] = resp.data[0]["PitchID"]
                st.session_state["last_pitch_summary"] = f"{pitch_called} ({st.session_state['balls']}-{st.session_state['strikes']})"
                st.success("Saved (Ball).")
                st.rerun()
    with c2:
        if st.button("Strike Swing Miss"):
            st.session_state["strikes"] = min(3, st.session_state["strikes"] + 1)
            pitch_called = "Strike Swing Miss"
            resp = supabase.table("Pitches").insert({
                "AtBatID": atbat_id,
                "PitchNo": pno,
                "PitchOfAB": poab,
                "PitchType": None,
                "Velocity": None,
                "Zone": None,
                "PitchCalled": pitch_called,
                "WEL": compute_wel(st.session_state["balls"], st.session_state["strikes"]),
                "Balls": st.session_state["balls"],
                "Strikes": st.session_state["strikes"],
                "TaggedHit": None,
                "HitDirection": None,
                "KPI": None
            }).execute()
            if resp.data:
                st.session_state["pitch_history"].append(resp.data[0]["PitchID"])
                st.session_state["last_saved_pitch_id"] = resp.data[0]["PitchID"]
                st.session_state["last_pitch_summary"] = f"{pitch_called} ({st.session_state['balls']}-{st.session_state['strikes']})"
                st.success("Saved (Swing Miss).")
                st.rerun()
    with c3:
        if st.button("Foul Ball"):
            if st.session_state["strikes"] < 2:
                st.session_state["strikes"] += 1
            pitch_called = "Foul Ball"
            resp = supabase.table("Pitches").insert({
                "AtBatID": atbat_id,
                "PitchNo": pno,
                "PitchOfAB": poab,
                "PitchType": None,
                "Velocity": None,
                "Zone": None,
                "PitchCalled": pitch_called,
                "WEL": compute_wel(st.session_state["balls"], st.session_state["strikes"]),
                "Balls": st.session_state["balls"],
                "Strikes": st.session_state["strikes"],
                "TaggedHit": None,
                "HitDirection": None,
                "KPI": None
            }).execute()
            if resp.data:
                st.session_state["pitch_history"].append(resp.data[0]["PitchID"])
                st.session_state["last_saved_pitch_id"] = resp.data[0]["PitchID"]
                st.session_state["last_pitch_summary"] = f"{pitch_called} ({st.session_state['balls']}-{st.session_state['strikes']})"
                st.success("Saved (Foul).")
                st.rerun()

    st.markdown("---")
    st.markdown("**Manual pitch entry (detail)**")
    with st.form("manual_pitch_form"):
        m_ptype = st.selectbox("Pitch Type", ["Fastball","Changeup","Curveball","Slider"], key="m_ptype")
        m_vel = st.number_input("Velocity (mph)", min_value=0.0, step=0.1, key="m_vel")
        m_zone = st.selectbox("Zone (1-14 or None)", ["None"] + [str(i) for i in range(1,15)], key="m_zone")
        m_called = st.selectbox("Pitch Called", ["Ball Called","Strike Called","Strike Swing Miss","Foul Ball","In Play"], key="m_called")
        m_tagged = st.selectbox("Tagged Hit", ["None","Bunt","Flyball","Groundball","Linedrive"], key="m_tagged")
        m_hitdir = st.selectbox("Hit Direction", ["None","3-4 Hole","5-6 Hole","Catcher","Center Field","First Base","Left Center","Left Field","Middle","Pitcher","Right Center","Right Field","Second Base","Short Stop","Third Base"], key="m_hitdir")
        submit_pitch = st.form_submit_button("Save Manual Pitch")

    if submit_pitch:
        # Update count according to rules
        if m_called == "Ball Called":
            st.session_state["balls"] = min(4, st.session_state["balls"] + 1)
        elif m_called in ["Strike Called","Strike Swing Miss"]:
            st.session_state["strikes"] = min(3, st.session_state["strikes"] + 1)
        elif m_called == "Foul Ball" and st.session_state["strikes"] < 2:
            st.session_state["strikes"] += 1
        elif m_called == "In Play":
            # treat as strike per coach note
            if st.session_state["strikes"] < 2:
                st.session_state["strikes"] += 1

        wel_val = compute_wel(st.session_state["balls"], st.session_state["strikes"])
        zone_val = None if m_zone == "None" else int(m_zone)
        tagged_val = None if m_tagged == "None" else m_tagged
        hitdir_val = None if m_hitdir == "None" else m_hitdir

        pitch_data = {
            "AtBatID": atbat_id,
            "PitchNo": pno,
            "PitchOfAB": poab,
            "PitchType": m_ptype,
            "Velocity": safe_float(m_vel),
            "Zone": zone_val,
            "PitchCalled": m_called,
            "WEL": wel_val,
            "Balls": int(st.session_state["balls"]),
            "Strikes": int(st.session_state["strikes"]),
            "TaggedHit": tagged_val,
            "HitDirection": hitdir_val,
            "KPI": None
        }

        try:
            r = supabase.table("Pitches").insert(pitch_data).execute()
            if r.data:
                pid = r.data[0]["PitchID"]
                st.session_state["pitch_history"].append(pid)
                st.session_state["last_saved_pitch_id"] = pid
                st.session_state["last_pitch_summary"] = f"{m_ptype} {m_vel} — {m_called} ({st.session_state['balls']}-{st.session_state['strikes']})"
                st.success("Manual pitch saved.")
                st.rerun()
            else:
                st.error("Pitch not saved. Check DB schema.")
        except Exception as e:
            st.error(f"Error inserting pitch: {e}")

# ---------------------------
#  4) Runner Events (multi-select)
# ---------------------------
st.header("4 — Runner Events (tie to last pitch)")

# Determine current pitch id: prefer last_saved_pitch_id then last of pitch_history
current_pid = st.session_state.get("last_saved_pitch_id") or (st.session_state["pitch_history"][-1] if st.session_state["pitch_history"] else None)

if not current_pid:
    st.info("Log at least one pitch to attach runner events.")
else:
    st.write(f"Attaching runner events to PitchID: {current_pid}")
    players = supabase.table("Players").select("PlayerID, Name").order("Name", desc=False).execute().data or []
    names = [p["Name"] for p in players]
    sel_names = st.multiselect("Select one or more runners", ["-- none --"] + names, default=[])
    start_base = st.selectbox("Start base", [1,2,3,4], index=0)
    end_base = st.selectbox("End base (0=None)", [0,1,2,3,4], index=0, format_func=lambda x: "None" if x==0 else str(x))
    event_type = st.selectbox("Event Type", ["Stolen Base","Caught Stealing","Out on Play","Pickoff","Advanced on Hit","Other"])
    out_recorded = st.selectbox("Out Recorded", ["No","Yes"])
    if st.button("Save Runner Events"):
        if not sel_names:
            st.warning("Select at least one runner.")
        else:
            created = 0
            for nm in sel_names:
                if nm == "-- none --":
                    continue
                pid = next((p["PlayerID"] for p in players if p["Name"] == nm), None)
                if pid is None:
                    continue
                payload = {
                    "PitchID": current_pid,
                    "RunnerID": pid,
                    "StartBase": int(start_base),
                    "EndBase": None if end_base == 0 else int(end_base),
                    "EventType": event_type,
                    "OutRecorded": True if out_recorded == "Yes" else False
                }
                try:
                    rr = supabase.table("RunnerEvents").insert(payload).execute()
                    if rr.data:
                        created += 1
                except Exception as e:
                    st.error(f"Failed for {nm}: {e}")
            if created:
                st.success(f"Saved {created} runner events.")
            else:
                st.warning("No runner events saved.")

# ---------------------------
# Footer / Tips
# ---------------------------
st.markdown("---")
st.caption("Notes: Setup lineup and pitchers first. Use quick buttons for speed. Manual pitch for detail. Undo to correct mistakes.")


