import streamlit as st
from supabase import create_client
from datetime import date

# --- Supabase connection ---
url = "https://oposlbpvxpbjsfqmiuly.supabase.co"   
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9wb3NsYnB2eHBianNmcW1pdWx5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTc4ODA2OTMsImV4cCI6MjA3MzQ1NjY5M30.J0Gs8JWoxpKAaUZFiiIy-gJ5EUmRW3aSdNkuLMYh0QI"                      
supabase = create_client(url, key)

st.title("Baseball Game Tracker")

# --------------------
# 1. Select or Add Game
# --------------------
st.header("Game Selection")

games = supabase.table("Games").select("*").execute().data
game_options = {f"{g['GameDate']} - {g['HomeTeam']} vs {g['AwayTeam']}": g["GameID"] for g in games}

selected_game = st.selectbox("Select Game", ["-- Add New Game --"] + list(game_options.keys()))

if selected_game == "-- Add New Game --":
    st.subheader("Add a New Game")
    home_team = st.text_input("Home Team")
    away_team = st.text_input("Away Team")
    game_date = st.date_input("Game Date", date.today())

    if st.button("Save Game"):
        response = supabase.table("Games").insert({
            "HomeTeam": home_team,
            "AwayTeam": away_team,
            "GameDate": str(game_date)
        }).execute()
        st.success("Game saved! Refresh and select it from the dropdown.")
        st.stop()
    else:
        st.stop()
else:
    game_id = game_options[selected_game]
    st.success(f"Selected game: {selected_game}")

# --------------------
# 2. Select or Add AtBat
# --------------------
st.header("AtBat Selection")

atbats = supabase.table("AtBats").select("*").eq("GameID", game_id).execute().data
atbat_options = {
    f"Inning {a['Inning']} - Batter {a['BatterID']} vs Pitcher {a['PitcherID']}": a["AtBatID"]
    for a in atbats
}

selected_atbat = st.selectbox("Select AtBat", ["-- Add New AtBat --"] + list(atbat_options.keys()))

if selected_atbat == "-- Add New AtBat --":
    st.subheader("Add a New AtBat")

    # Get selected game info for team options
    game_data = supabase.table("Games").select("HomeTeam, AwayTeam").eq("GameID", game_id).execute().data[0]
    home_team = game_data["HomeTeam"]
    away_team = game_data["AwayTeam"]

    # Batter input
    batter_name = st.text_input("Batter Name")
    batter_team_choice = st.selectbox("Batter Team", [home_team, away_team])
    batter_side = st.selectbox("Bats", ["Right", "Left", "Switch"])

    # Determine opposing team for pitcher
    pitcher_team_choice = away_team if batter_team_choice == home_team else home_team
    st.write(f"Pitcher Team: **{pitcher_team_choice}**")

    # Pitcher input
    pitcher_name = st.text_input("Pitcher Name")
    pitcher_throws = st.selectbox("Throws", ["Right", "Left"])

    # Other AtBat details
    inning = st.number_input("Inning", min_value=1, step=1)
    batter_order = st.number_input("Batter Order", min_value=1, step=1)
    lead_off = st.selectbox("Lead Off", ["Yes", "No"])
    lead_off_on = st.selectbox("Lead Off On", ["Yes", "No"])

    play_result = st.selectbox(
        "Play Result",
        [
            "1B", "2B", "3B", "AdditionalSpecial", "BatterInter", "CaughtStealing",
            "DoublePlay", "DropThirdStrike", "Error", "FC", "FlyOut", "GroundOut",
            "HitByPitch", "HR", "OutOnPlay", "PickOff", "SAC", "SACFly",
            "Strikeout", "Walk"
        ]
    )

    runs_scored = st.number_input("Runs Scored", min_value=0, step=1)
    earned_runs = st.number_input("Earned Runs", min_value=0, step=1)
    korbb = st.selectbox("K or BB", ["Strikeout", "Walk", "None"])

    if st.button("Save AtBat"):
        # --- Ensure Batter exists ---
        batter = supabase.table("Players").select("PlayerID").eq("Name", batter_name).execute().data
        if batter:
            batter_id = batter[0]["PlayerID"]
        else:
            batter_insert = supabase.table("Players").insert({
                "Name": batter_name,
                "Team": batter_team_choice,
                "Bats": batter_side
            }).execute().data
            batter_id = batter_insert[0]["PlayerID"]

        # --- Ensure Pitcher exists ---
        pitcher = supabase.table("Players").select("PlayerID").eq("Name", pitcher_name).execute().data
        if pitcher:
            pitcher_id = pitcher[0]["PlayerID"]
        else:
            pitcher_insert = supabase.table("Players").insert({
                "Name": pitcher_name,
                "Team": pitcher_team_choice,
                "Throws": pitcher_throws
            }).execute().data
            pitcher_id = pitcher_insert[0]["PlayerID"]

        # --- Save AtBat ---
        response = supabase.table("AtBats").insert({
            "GameID": game_id,
            "BatterID": batter_id,
            "PitcherID": pitcher_id,
            "Inning": inning,
            "BatterOrder": batter_order,
            "LeadOff": lead_off == "Yes",
            "LeadOffOn": lead_off_on == "Yes",
            "PlayResult": play_result,
            "RunsScored": runs_scored,
            "EarnedRuns": earned_runs,
            "KorBB": korbb
        }).execute()

        st.success("AtBat saved! Refresh and select it from the dropdown.")
        st.stop()
    else:
        st.stop()
else:
    atbat_id = atbat_options[selected_atbat]
    st.success(f"Selected AtBat: {selected_atbat}")



# --------------------
# 3. Add Pitch
# --------------------
st.header("Pitch Entry")

pitch_id = None  # Initialize safely for later use (and runner events)

if selected_atbat != "-- Add New AtBat --":
    atbat_id = atbat_options[selected_atbat]

    # --- Get pitcher ID and batter ID from current AtBat ---
    atbat_data = supabase.table("AtBats").select("PitcherID, BatterID").eq("AtBatID", atbat_id).execute().data[0]
    pitcher_id = atbat_data["PitcherID"]
    batter_id = atbat_data["BatterID"]

    # --- Determine next pitch numbers ---
    all_pitches_pitcher = supabase.table("Pitches").select("PitchNo").execute().data
    next_pitch_no = len(all_pitches_pitcher) + 1 if all_pitches_pitcher else 1

    atbat_pitches = supabase.table("Pitches").select("PitchOfAB").eq("AtBatID", atbat_id).execute().data
    next_pitch_of_ab = len(atbat_pitches) + 1

    st.write(f"Next Pitch No: **{next_pitch_no}**  |  Pitch of AtBat: **{next_pitch_of_ab}**")

    # --- Input fields ---
    pitch_type = st.selectbox("Pitch Type", ["Fastball", "Changeup", "Curveball", "Slider"])
    velocity = st.number_input("Velocity (mph)", min_value=0.0, step=0.1)

    zone = st.selectbox("Zone (1–14 or None)", ["None"] + [str(i) for i in range(1, 15)])

    pitch_called = st.selectbox(
        "Pitch Result (PitchCalled)",
        ["Ball Called", "Foul Ball", "In Play", "Strike Called", "Strike Swing Miss"]
    )

    wel = st.selectbox("WEL", ["None", "W", "E", "L"])
    balls = st.number_input("Balls", min_value=0, max_value=4, step=1)
    strikes = st.number_input("Strikes", min_value=0, max_value=3, step=1)

    tagged_hit = st.selectbox("Tagged Hit", ["None", "Bunt", "Flyball", "Groundball", "Linedrive"])
    hit_direction = st.selectbox(
        "Hit Direction",
        [
            "None", "3-4 Hole", "5-6 Hole", "Catcher", "Center Field", "First Base",
            "Left Center", "Left Field", "Middle", "Pitcher", "Right Center",
            "Right Field", "Second Base", "Short Stop", "Third Base"
        ]
    )

    custom = st.text_input("KPI / Notes (Custom)")

    # --- Save Pitch button and logic ---
    if st.button("Save Pitch"):
        # Convert dropdowns with "None" into actual None values
        zone_value = None if zone == "None" else int(zone)
        wel_value = None if wel == "None" else wel
        tagged_value = None if tagged_hit == "None" else tagged_hit
        hit_dir_value = None if hit_direction == "None" else hit_direction

        # Insert new pitch into Supabase
        response = supabase.table("Pitches").insert({
            "AtBatID": atbat_id,
            "PitchNo": next_pitch_no,
            "PitchOfAB": next_pitch_of_ab,
            "PitchType": pitch_type,
            "Velocity": velocity,
            "Zone": zone_value,
            "PitchCalled": pitch_called,
            "WEL": wel_value,
            "Balls": balls,
            "Strikes": strikes,
            "TaggedHit": tagged_value,
            "HitDirection": hit_dir_value,
            "KPI": custom
        }).execute()

        # Handle the response safely *inside* the button block
        if response.data:
            pitch_id = response.data[0]["PitchID"]
            st.session_state["last_pitch_id"] = pitch_id  # store in session for runner events
            st.success(f"Pitch saved successfully! (Pitch ID: {pitch_id})")
        else:
            st.error("Pitch not saved. Please check your inputs or Supabase connection.")

else:
    st.info("Select an AtBat before entering pitches.")



# --------------------
# 4. Runner Events
# --------------------
st.header("Runner Events")

# Retrieve last saved pitch ID
pitch_id = st.session_state.get("last_pitch_id", None)

if pitch_id:
    # --- Load players for dropdown ---
    players = supabase.table("Players").select("PlayerID, Name").execute().data
    player_options = {p["Name"]: p["PlayerID"] for p in players}

    selected_runner = st.selectbox("Select Runner", ["-- Select Player --"] + list(player_options.keys()))

    # --- Base selections as integers ---
    # Convention: 1 = first base, 2 = second, 3 = third, 4 = home plate
    base_options = [1, 2, 3, 4]
    start_base = st.selectbox("Start Base", base_options)
    end_base = st.selectbox("End Base", base_options + [0], format_func=lambda x: "None" if x == 0 else str(x))

    # --- Event type dropdown ---
    event_type = st.selectbox(
        "Event Type",
        ["Stolen Base", "Caught Stealing", "Out on Play", "Pickoff", "Advanced on Hit", "Other"]
    )

    # --- Out recorded dropdown ---
    out_recorded = st.selectbox("Out Recorded", ["No", "Yes"])

    # --- Save button ---
    if st.button("Save Runner Event"):
        if selected_runner == "-- Select Player --":
            st.warning("Please select a runner before saving.")
        else:
            runner_id = player_options[selected_runner]

            # Prepare data for insertion
            response = supabase.table("RunnerEvents").insert({
                "PitchID": pitch_id,
                "RunnerID": runner_id,
                "StartBase": start_base,
                "EndBase": None if end_base == 0 else end_base,
                "EventType": event_type,
                "OutRecorded": True if out_recorded == "Yes" else False
            }).execute()

            if response.data:
                st.success("Runner event saved successfully!")
            else:
                st.error("Failed to save runner event. Please try again.")
else:
    st.info("Save a pitch first before entering runner events.")