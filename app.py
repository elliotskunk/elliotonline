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
                item (required), price (required, float in GBP), date (DD/MM/YYYY), 
                storage_location, box_label, total_qty (integer), place_bought.
                Return array even for single items. Include any available fields."""},
                {"role": "user", "content": text}
            ],
            temperature=0.3
        )
        
        content = response.choices[0].message.content
        if '```json' in content:
            content = content.split('```json')[1].split('```')[0]

        raw_entries = json.loads(content)
        if not isinstance(raw_entries, list):
            raw_entries = [raw_entries]

        parsed_entries = []
        for entry in raw_entries:
            try:
                # Validate required fields
                errors = []
                if 'item' not in entry:
                    errors.append("Missing required field: item")
                if 'price' not in entry:
                    errors.append("Missing required field: price")
                
                # Try to convert numeric fields
                try:
                    price = float(entry.get('price', 0))
                except (ValueError, TypeError):
                    errors.append("Invalid price format")
                
                try:
                    total_qty = int(entry.get('total_qty', 1))
                except (ValueError, TypeError):
                    errors.append("Invalid quantity format")
                    total_qty = 1

                # Create entry dictionary with defaults
                parsed_entry = {
                    'item': entry.get('item', 'Unknown Item'),
                    'price': price,
                    'date': entry.get('date') or datetime.now().strftime("%d/%m/%Y"),
                    'storage_location': entry.get('storage_location', 'Not specified'),
                    'category': entry.get('category', 'Uncategorized'),
                    'box_label': entry.get('box_label', ''),
                    'total_qty': total_qty,
                    'place_bought': entry.get('place_bought', 'Unknown location'),
                    'errors': errors
                }
                
                parsed_entries.append(parsed_entry)

            except Exception as e:
                print(f"Error parsing entry: {str(e)}")
                parsed_entries.append({
                    'error': f"Parse error: {str(e)}",
                    'raw_entry': str(entry)
                })
                continue

        return parsed_entries

    except Exception as e:
        print(f"Parsing Error: {str(e)}")
        return [{'error': f"System error: {str(e)}", 'raw_entry': content}]

@app.route("/", methods=["GET", "POST"])
def home():
    processed_entries = []
    update_result = None
    
    if request.method == "POST":
        # Handle updates
        if 'update_id' in request.form:
            update_id = request.form['update_id'].strip()
            try:
                # Find the row to update
                records = sheet.get_all_records()
                cell = sheet.find(update_id, in_column=1)  # Column A is ID
                
                # Build update dictionary
                updates = {}
                if request.form['catalogue_number']:
                    updates[3] = request.form['catalogue_number']  # Column D
                if request.form['storage_location']:
                    updates[4] = request.form['storage_location']  # Column E
                if request.form['box_label']:
                    updates[5] = request.form['box_label']  # Column F
                if request.form['remaining_qty']:
                    updates[8] = float(request.form['remaining_qty'])  # Column I
                if request.form['place_bought']:
                    updates[10] = request.form['place_bought']  # Column K
                
                if updates:
                    # Update cells using batch_update
                    requests = [{
                        'range': f"{cell.row}:{cell.row}",
                        'values': [list(updates.values())]
                    }]
                    sheet.batch_update(requests)
                    
                    update_result = f"✅ Successfully updated entry {update_id}"
                else:
                    update_result = "⚠️ No fields provided for update"
                    
            except gspread.exceptions.CellNotFound:
                update_result = "⚠️ Error: Entry ID not found"
            except Exception as e:
                update_result = f"⚠️ Update error: {str(e)}"
        
        # Handle new entries
        else:
            input_text = request.form["input_text"]
            parsed_entries = parse_input_with_deepseek(input_text)
            # ... (keep existing entry processing code)

    return render_template("index.html", 
                         entries=processed_entries,
                         update_result=update_result)

if __name__ == "__main__":
    app.run(debug=True)