import os
import re
import secrets
import sqlite3

from flask import Flask, render_template, request, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
DATABASE_PATH = os.path.join(app.instance_path, "traveler.sqlite3")


def get_database():
    os.makedirs(app.instance_path, exist_ok=True)
    database = sqlite3.connect(DATABASE_PATH)
    database.row_factory = sqlite3.Row
    return database


def initialize_database():
    with get_database() as database:
        database.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


@app.before_request
def ensure_database():
    if not getattr(app, "database_initialized", False):
        initialize_database()
        app.database_initialized = True


@app.context_processor
def inject_current_user():
    return {"current_user": session.get("user")}

# -----------------------------
# NLP - Extract Travel Details
# -----------------------------
def extract_travel_details(text):

    text_lower = text.lower()

    details = {
        "destination": "Not mentioned",
        "days": "Not mentioned",
        "budget": "Not mentioned",
        "interest": []
    }

    # Destination
    places = [
        "ooty", "coimbatore", "chennai",
        "kodaikanal", "kerala", "bangalore",
        "goa", "mysore", "madurai"
    ]

    for place in places:
        if place in text_lower:
            details["destination"] = place.title()

    # Days
    day_match = re.search(r'(\d+)\s*(day|days)', text_lower)

    if day_match:
        details["days"] = day_match.group(1) + " Days"

    # Budget
    budget_match = re.search(
        r'₹\s*(\d+(?:,\d+)*)|\b(\d+(?:,\d+)*)\s*(?:rupees?|inr)\b|\bbudget\s*(?:of\s*)?₹?\s*(\d+(?:,\d+)*)',
        text,
        re.IGNORECASE
    )

    if budget_match:
        amount = next(group for group in budget_match.groups() if group)
        details["budget"] = "₹" + amount

    # Interests
    interests = {
        "nature": ["nature", "forest", "mountain"],
        "photography": ["photography", "photo"],
        "beach": ["beach", "sea"],
        "adventure": ["adventure", "trekking"],
        "historical": ["history", "historical", "temple"]
    }

    for category, words in interests.items():
        for word in words:
            if word in text_lower and category not in details["interest"]:
                details["interest"].append(category)

    return details


# Day plans are suggestions only; opening hours and conditions can change.
TRIP_GUIDES = {
    "Ooty": [
        ("Botanical Garden", "Ooty Lake", "Charing Cross"),
        ("Doddabetta Peak", "Tea Factory", "Rose Garden"),
        ("Pykara Falls", "Pine Forest", "Local market"),
        ("Coonoor viewpoint", "Nilgiri Mountain Railway", "Tea tasting"),
    ],
    "Kodaikanal": [
        ("Coaker's Walk", "Bryant Park", "Kodaikanal Lake"),
        ("Pillar Rocks", "Guna Caves area", "Pine Forest"),
        ("Silver Cascade Falls", "Poombarai village", "Homemade chocolate shops"),
    ],
    "Chennai": [
        ("Kapaleeshwarar Temple", "San Thome Basilica", "Marina Beach"),
        ("Government Museum", "Fort St. George", "George Town food walk"),
        ("DakshinaChitra", "Elliot's Beach", "Mylapore evening walk"),
    ],
    "Coimbatore": [
        ("Marudhamalai Temple", "Gass Forest Museum", "RS Puram food stop"),
        ("Isha Yoga Center", "Adiyogi area", "Perur Temple"),
        ("Siruvani viewpoint", "VOC Park", "Town market"),
    ],
    "Kerala": [
        ("Fort Kochi lanes", "Chinese fishing nets", "Mattancherry Palace"),
        ("Alleppey backwaters", "Village canoe ride", "Sunset waterfront"),
        ("Munnar tea gardens", "Tea Museum", "Local spice market"),
    ],
    "Bangalore": [
        ("Lalbagh Botanical Garden", "Tipu Sultan's Summer Palace", "VV Puram food street"),
        ("Cubbon Park", "Bangalore Palace", "Church Street"),
        ("Bannerghatta nature area", "National Gallery of Modern Art", "Indiranagar cafes"),
    ],
    "Goa": [
        ("Old Goa churches", "Fontainhas heritage quarter", "Panaji riverside"),
        ("North Goa beach morning", "Fort Aguada", "Sunset at the shore"),
        ("South Goa beach", "Local spice farm", "Beachside market"),
    ],
    "Mysore": [
        ("Mysore Palace", "Devaraja Market", "St. Philomena's Cathedral"),
        ("Chamundi Hill", "Sand Sculpture Museum", "Brindavan Gardens"),
        ("Jaganmohan Palace", "Karanji Lake", "Mysore silk market"),
    ],
    "Madurai": [
        ("Meenakshi Amman Temple", "Puthu Mandapam", "Vilakkuthoon food walk"),
        ("Thirumalai Nayakkar Palace", "Gandhi Memorial Museum", "Vandiyur Teppakulam"),
        ("Alagar Kovil", "Pazhamudircholai", "Local jasmine market"),
    ],
}

DAILY_ESTIMATES = {
    "Ooty": 2200, "Kodaikanal": 2200, "Chennai": 2500,
    "Coimbatore": 2000, "Kerala": 2800, "Bangalore": 2800,
    "Goa": 3000, "Mysore": 2200, "Madurai": 2000,
}


def build_trip_plan(details, language):
    destination = details["destination"]
    requested_days = int(details["days"].split()[0]) if details["days"] != "Not mentioned" else 3
    day_count = min(max(requested_days, 1), 7)
    guide = TRIP_GUIDES.get(destination, TRIP_GUIDES["Ooty"])
    day_labels = ("காலை", "மதியம்", "மாலை") if language == "Tamil" else ("Morning", "Afternoon", "Evening")

    itinerary = []
    for index in range(day_count):
        stops = guide[index % len(guide)]
        itinerary.append({
            "day": index + 1,
            "morning": {"label": day_labels[0], "place": stops[0]},
            "afternoon": {"label": day_labels[1], "place": stops[1]},
            "evening": {"label": day_labels[2], "place": stops[2]},
        })

    estimate_per_day = DAILY_ESTIMATES.get(destination, 2200)
    budget_text = details["budget"]
    budget_total = int(budget_text.replace("₹", "").replace(",", "")) if budget_text != "Not mentioned" else None
    budget_per_day = round(budget_total / day_count) if budget_total is not None else None
    interests = details["interest"]

    if language == "Tamil":
        tip = "இடங்களுக்குச் செல்லும் முன் திறந்திருக்கும் நேரத்தையும் பயண வழியையும் சரிபார்க்கவும்."
        if "nature" in interests:
            tip = "இயற்கை இடங்களுக்கு காலை நேரம் செல்லுங்கள்; வசதியான காலணியும் தண்ணீரும் எடுத்துச் செல்லுங்கள்."
        elif "photography" in interests:
            tip = "புகைப்படங்களுக்கு காலை அல்லது மாலை ஒளி சிறந்தது; சில இடங்களில் புகைப்பட விதிகளைச் சரிபார்க்கவும்."
        elif "beach" in interests:
            tip = "கடற்கரையில் கொடிகள் மற்றும் உள்ளூர் பாதுகாப்பு அறிவுறுத்தல்களைப் பின்பற்றுங்கள்."
        elif "adventure" in interests:
            tip = "சாகச செயல்களுக்கு முன்பதிவு, வானிலை, பாதுகாப்பு உபகரணங்களை முன்கூட்டியே சரிபார்க்கவும்."
        elif "historical" in interests:
            tip = "வரலாற்று இடங்களின் திறந்திருக்கும் நேரத்தையும் உடை விதிகளையும் முன்கூட்டியே பாருங்கள்."
        reply = (
            f"உங்கள் பயணத் திட்டம்: {destination}\n"
            f"காலம்: {day_count} நாட்கள்\n"
            f"தினசரி செலவு மதிப்பீடு: சுமார் ₹{estimate_per_day:,} (ஒருவருக்கு; தங்குமிடம் மற்றும் பயண முறையைப் பொறுத்து மாறலாம்).\n"
            f"குறிப்பு: {tip}"
        )
    else:
        tip = "Check local opening hours and travel times before setting out."
        tips = {
            "nature": "Start nature stops early; bring water and comfortable walking shoes.",
            "photography": "Morning and late-afternoon light is best; check photo rules at each site.",
            "beach": "Follow local flags and lifeguard guidance at the beach.",
            "adventure": "Confirm bookings, weather, and safety equipment before adventure activities.",
            "historical": "Check opening hours and visitor guidance at heritage sites before you go.",
        }
        for interest, interest_tip in tips.items():
            if interest in interests:
                tip = interest_tip
                break
        reply = (
            f"Your trip plan for {destination}\n"
            f"Duration: {day_count} days\n"
            f"Estimated daily spend: about ₹{estimate_per_day:,} per person; actual costs vary by stay and transport.\n"
            f"Travel tip: {tip}"
        )

    return {
        "reply": reply,
        "itinerary": itinerary,
        "estimate": {
            "per_day": estimate_per_day,
            "total": estimate_per_day * day_count,
            "budget_per_day": budget_per_day,
            "within_budget": budget_per_day >= estimate_per_day if budget_per_day is not None else None,
        },
        "days": day_count,
    }


def public_user(user):
    return {"name": user["name"], "email": user["email"]}


@app.route("/auth/me", methods=["GET"])
def auth_me():
    return jsonify({"user": session.get("user")})


@app.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not name or len(name) > 80:
        return jsonify({"error": "Enter your name (up to 80 characters)."}), 400
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return jsonify({"error": "Enter a valid email address."}), 400
    if len(password) < 8:
        return jsonify({"error": "Use a password with at least 8 characters."}), 400

    try:
        with get_database() as database:
            cursor = database.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password)),
            )
            user = database.execute(
                "SELECT name, email FROM users WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
    except sqlite3.IntegrityError:
        return jsonify({"error": "An account with this email already exists. Please sign in."}), 409

    session.clear()
    session["user"] = public_user(user)
    return jsonify({"user": session["user"]}), 201


@app.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    with get_database() as database:
        user = database.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Email or password is incorrect."}), 401

    session.clear()
    session["user"] = public_user(user)
    return jsonify({"user": session["user"]})


@app.route("/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()
    language = data.get("language", "English")
    if not message:
        return jsonify({"error": "Send a message to start chatting."}), 400

    details = extract_travel_details(message)
    normalized = message.lower()
    greeting = any(word in normalized for word in ("hello", "hi", "hey", "வணக்கம்", "ஹாய்"))
    if language == "Tamil":
        if greeting:
            reply = "வணக்கம்! பயண இடம், நாட்கள், செலவு வரம்பு அல்லது பார்க்க விரும்பும் இடங்களைச் சொல்லுங்கள். அதற்கேற்ற திட்டம் உருவாக்க உதவுகிறேன்."
        elif details["destination"] == "Not mentioned":
            reply = "எந்த இடத்திற்குப் பயணம் செய்ய விரும்புகிறீர்கள்? உதாரணம்: ‘ஊட்டி 3 நாட்கள், ₹10000, இயற்கை’. இடம், நாட்கள், budget சொன்னால் திட்டம் தருகிறேன்."
        else:
            plan = build_trip_plan(details, language)
            stops = plan["itinerary"][0]
            reply = (
                f"{details['destination']} பயணத்திற்கு உதவுகிறேன்! {plan['days']} நாள் திட்டம் தயார். "
                f"முதல் நாள்: {stops['morning']['place']}, {stops['afternoon']['place']}, {stops['evening']['place']}. "
                f"ஒருவருக்கு தினசரி செலவு சுமார் ₹{plan['estimate']['per_day']:,}. "
                "முழு நாள் வாரியான திட்டத்துக்கு ‘Build my trip plan’-ஐத் தேர்வு செய்யுங்கள்."
            )
    elif greeting:
        reply = "Hi! I can help with destinations, day plans, and a rough daily budget. Tell me where you’re going, how many days, and what you enjoy."
    elif details["destination"] == "Not mentioned":
        reply = "Which destination are you considering? Share the place, trip length, and interests. For example: ‘Ooty for 3 days, nature and photography.’"
    else:
        plan = build_trip_plan(details, language)
        stops = plan["itinerary"][0]
        reply = (
            f"I can help plan {details['destination']} for {plan['days']} days. "
            f"Start with {stops['morning']['place']}, then {stops['afternoon']['place']}, "
            f"and finish at {stops['evening']['place']}. Estimated spend is about "
            f"₹{plan['estimate']['per_day']:,} per person per day. "
            "Use ‘Build my trip plan’ for the complete daily itinerary."
        )

    return jsonify({"reply": reply, "details": details})


# -----------------------------
# AI Travel Assistant
# -----------------------------
@app.route("/assistant", methods=["POST"])
def assistant():

    data = request.get_json(silent=True) or {}

    message = data.get("message", "")
    language = data.get("language", "English")

    details = extract_travel_details(message)

    plan = build_trip_plan(details, language)

    return jsonify({
        "reply": plan["reply"],
        "details": details,
        "itinerary": plan["itinerary"],
        "estimate": plan["estimate"],
        "days": plan["days"],
    })


# -----------------------------
# Customer Review Sentiment
# -----------------------------
@app.route("/review", methods=["POST"])
def review():

    data = request.json

    review_text = data.get("review", "").lower()

    positive_words = [
        "good", "great", "excellent",
        "amazing", "beautiful", "clean",
        "comfortable", "nice", "best"
    ]

    negative_words = [
        "bad", "poor", "dirty",
        "worst", "expensive", "slow",
        "uncomfortable", "terrible"
    ]

    positive = sum(word in review_text for word in positive_words)
    negative = sum(word in review_text for word in negative_words)

    if positive > negative:
        sentiment = "Positive 😊"

    elif negative > positive:
        sentiment = "Negative 😞"

    else:
        sentiment = "Neutral 😐"

    return jsonify({
        "sentiment": sentiment
    })


# -----------------------------
# Main Page
# -----------------------------
@app.route("/")
def home():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)