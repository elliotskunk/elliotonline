from flask import Flask, request, render_template
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from openai import OpenAI
from datetime import datetime
import os
from dotenv import load_dotenv
from pathlib import Path
import json
import speech_recognition as sr

# Load environment variables
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)


# Initialize DeepSeek client
deepseek_client = OpenAI(  # CHANGED VARIABLE NAME
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://api.deepseek.com"
)

# Google Sheets setup
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
gsheet_client = gspread.authorize(creds)

# Open Google Sheet and worksheet
sheet = gsheet_client.open("DS ELLIOTONLINE").worksheet("Inventory")

app = Flask(__name__)


# For web audio input
from werkzeug.utils import secure_filename

def convert_speech_to_text(audio_path):
    """Convert audio file to text using Google's speech recognition"""
    r = sr.Recognizer()
    with sr.AudioFile(audio_path) as source:
        audio = r.record(source)
        try:
            return r.recognize_google(audio)
        except sr.UnknownValueError:
            return "Could not understand audio"
        except sr.RequestError as e:
            return f"Speech recognition error: {e}"

@app.route('/upload', methods=['POST'])
def upload_audio():
    try:
        audio_file = request.files['audio']
        filename = secure_filename(audio_file.filename)
        audio_file.save(filename)
        # Use speech recognition library here
        text = convert_speech_to_text(filename)
        return text
    finally:
        if os.path.exists(filename):
            os.remove(filename)  # Delete audio file after processing

def parse_input_with_deepseek(text):
    """Parse inventory input using DeepSeek API with flexible fields"""
    content = ""
    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": """Extract inventory details as valid JSON array with these keys:
                item (required), price (required, float in GBP, correctly extracted from text without misinterpretation), 
                date (DD/MM/YYYY), storage_location, box_label, total_qty (integer), place_bought.
                Ensure the price is extracted accurately and does not get inflated."""},
                {"role": "user", "content": text}
            ],
            temperature=0.3
        )
        
        content = response.choices[0].message.content
        if '```json' in content:
            content = content.split('```json')[1].split('```')[0]

        try:
            raw_entries = json.loads(content)
        except json.JSONDecodeError:
            return [{'error': "Invalid JSON format", 'raw_entry': content}]

        if not isinstance(raw_entries, list):
            raw_entries = [raw_entries]

        parsed_entries = []
        for entry in raw_entries:
            try:
                errors = []

                # Ensure required fields exist
                item = entry.get('item')
                if not item:
                    errors.append("Missing required field: item")

                # Convert price to float, handle errors
                try:
                    price = float(entry['price'])
                except (ValueError, TypeError, KeyError):
                    errors.append("Invalid price format")
                    price = 0.0

                # Convert quantity to integer, default to 1 if missing/invalid
                # Convert quantity to integer, default to 1 if missing/invalid
                try:
                    total_qty = int(entry['total_qty'])
                    if total_qty <= 0:
                        raise ValueError
                except (ValueError, TypeError, KeyError):
                    errors.append("Invalid quantity format, defaulting to 1")
                    total_qty = 1  # Default assumption

                # If we fixed the quantity, remove the error message
                if total_qty == 1 and "Invalid quantity format, defaulting to 1" in errors:
                    errors.remove("Invalid quantity format, defaulting to 1")


                # Assign defaults for missing fields

                remaining_qty = entry.get('remaining_qty')
                if remaining_qty is None:
                    remaining_qty = total_qty

                parsed_entry = {
                    'item': item or 'Unknown Item',
                    'price': price,
                    'date': entry.get('date') or datetime.now().strftime("%d/%m/%Y"),
                    'storage_location': entry.get('storage_location', 'Not specified') or 'Not specified',
                    'box_label': entry.get('box_label', '') or '',
                    'total_qty': total_qty,
                    'remaining_qty': remaining_qty,
                    'place_bought': entry.get('place_bought', 'Unknown location') or 'Unknown location',
                    'errors': errors
                }

                parsed_entries.append(parsed_entry)

            except Exception as e:
                print(f"Error parsing entry: {str(e)}")
                parsed_entries.append({
                    'error': f"Parse error: {str(e)}",
                    'raw_entry': str(entry)
                })

        return parsed_entries

    except Exception as e:
        print(f"Parsing Error: {str(e)}")
        return [{'error': f"System error: {str(e)}", 'raw_entry': content}]


@app.route("/", methods=["GET", "POST"])
def home():
    processed_entries = []
    update_result = None

    if request.method == "POST":
        if 'update_id' in request.form:
            try:
                update_id = request.form['update_id'].strip()
                # Process update logic here...
            except gspread.exceptions.CellNotFound:
                update_result = "⚠️ Error: Entry ID not found"
            except Exception as e:
                update_result = f"⚠️ Update error: {str(e)}"

        elif 'input_text' in request.form:
            input_text = request.form["input_text"]
            parsed_entries = parse_input_with_deepseek(input_text)

            print("DEBUG - parsed_entries:", parsed_entries)
            
            # Grab existing data so we know how many rows exist
            records = sheet.get_all_records()
            row_count = len(records) + 1

            for entry in parsed_entries:
                if entry.get("errors"):
                    continue  # Skip entries with errors

                new_id = f"ITEM-{row_count}"
                row_count += 1

                row_data = [
                    new_id, entry["item"], "", entry["storage_location"],
                    entry["box_label"], entry["price"], entry["total_qty"],
                    entry.get("remaining_qty", ""), entry["date"], entry["place_bought"]
                ]

                sheet.append_row(row_data)
                entry["id"] = new_id
                processed_entries.append(entry)

    return render_template("index.html", 
                           entries=processed_entries,
                           update_result=update_result)

print("Starting up the eBay Inventory Manager...")

if __name__ == "__main__":
    print("About to run the Flask app...")
    app.run(debug=True)
