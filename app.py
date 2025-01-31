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
from werkzeug.utils import secure_filename

# Load environment variables
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# Initialize DeepSeek client
deepseek_client = OpenAI(
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

def convert_speech_to_text(audio_path):
    """Convert audio file to text using Google's speech recognition."""
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
        text = convert_speech_to_text(filename)
        return text
    finally:
        if os.path.exists(filename):
            os.remove(filename)  # Clean up the audio file

def parse_input_with_deepseek(text):
    """Parse inventory input using DeepSeek API with flexible fields."""
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
            # Extract JSON between ```json ... ```
            content = content.split('```json')[1].split('```')[0]

        try:
            raw_entries = json.loads(content)
        except json.JSONDecodeError:
            return [{'error': "Invalid JSON format", 'raw_entry': content}]

        if not isinstance(raw_entries, list):
            raw_entries = [raw_entries]

        parsed_entries = []
        for entry in raw_entries:
            errors = []

            # Item
            item = entry.get('item')
            if not item:
                errors.append("Missing required field: item")

            # Price
            try:
                price = float(entry['price'])
            except (ValueError, TypeError, KeyError):
                errors.append("Invalid price format")
                price = 0.0

            # total_qty
            try:
                total_qty = int(entry['total_qty'])
                if total_qty <= 0:
                    raise ValueError
            except (ValueError, TypeError, KeyError):
                errors.append("Invalid quantity format, defaulting to 1")
                total_qty = 1

            # If we fixed the quantity, remove the standard error message
            if total_qty == 1 and "Invalid quantity format, defaulting to 1" in errors:
                errors.remove("Invalid quantity format, defaulting to 1")

            # remaining_qty defaults to total_qty if missing
            remaining_qty = entry.get('remaining_qty')
            if remaining_qty is None:
                remaining_qty = total_qty

            # Build parsed entry
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

        return parsed_entries

    except Exception as e:
        print(f"Parsing Error: {str(e)}")
        return [{'error': f"System error: {str(e)}", 'raw_entry': content}]

@app.route("/", methods=["GET", "POST"])
def home():
    processed_entries = []
    update_result = None

    if request.method == "POST":
        # 1) Handling an UPDATE (the 'Update Existing Entry' form)
        if 'update_id' in request.form:
            try:
                update_id = request.form['update_id'].strip()
                cell = sheet.find(update_id)  # Locate row by ID
                row_number = cell.row

                # Debug: Show all form data
                print("DEBUG - Form Data Received:", request.form)

                # Optional updates
                catalogue_number = request.form.get('catalogue_number', '').strip()
                new_storage_location = request.form.get('storage_location', '').strip()
                new_box_label = request.form.get('box_label', '').strip()
                new_place_bought = request.form.get('place_bought', '').strip()

                # We'll apply restock_qty or quantity_sold logic to total_qty & remaining_qty
                restock_qty = request.form.get('restock_qty', '').strip()
                quantity_sold = request.form.get('quantity_sold', '').strip()

                update_data = []

                # We want to read existing row data from the sheet
                # Columns reference (1-based indexing):
                #   A=1, B=2, C=3, D=4, E=5, F=6, G=7, H=8, I=9, J=10
                row_values = sheet.row_values(row_number)

                # For safety, pad the row values in case they're shorter
                while len(row_values) < 10:
                    row_values.append("")

                existing_catalogue = row_values[2]
                existing_storage_location = row_values[3]
                existing_box_label = row_values[4]
                existing_price = row_values[5]
                existing_total_qty = row_values[6]
                existing_remaining_qty = row_values[7]
                existing_place_bought = row_values[9]

                # Convert to numeric
                try:
                    existing_total_qty = int(existing_total_qty)
                except:
                    existing_total_qty = 1

                try:
                    existing_remaining_qty = int(existing_remaining_qty)
                except:
                    existing_remaining_qty = existing_total_qty

                # 2) Catalogue Number (Column C = index 3)
                if catalogue_number:
                    update_data.append((row_number, 3, catalogue_number))
                else:
                    catalogue_number = existing_catalogue

                # 3) Storage Location (Column D = index 4)
                if new_storage_location:
                    update_data.append((row_number, 4, new_storage_location))
                else:
                    new_storage_location = existing_storage_location

                # 4) Box Label (Column E = index 5)
                if new_box_label:
                    update_data.append((row_number, 5, new_box_label))
                else:
                    new_box_label = existing_box_label

                # 5) Place Bought (Column J = index 10)
                if new_place_bought:
                    update_data.append((row_number, 10, new_place_bought))
                else:
                    new_place_bought = existing_place_bought

                # 6) Restock & Sell Logic for Qtys
                #    existing_total_qty, existing_remaining_qty are our starting points
                if restock_qty:
                    try:
                        restock_qty = int(restock_qty)
                        # Add restock_qty to total_qty + remaining_qty
                        existing_total_qty += restock_qty
                        existing_remaining_qty += restock_qty
                    except ValueError:
                        pass  # Invalid restock_qty => ignore

                if quantity_sold:
                    try:
                        quantity_sold = int(quantity_sold)
                        # Subtract quantity_sold from remaining_qty only
                        existing_remaining_qty -= quantity_sold
                        if existing_remaining_qty < 0:
                            existing_remaining_qty = 0  # clamp to 0 if oversold
                    except ValueError:
                        pass  # Invalid quantity_sold => ignore

                # Now push updated total_qty and remaining_qty to the sheet
                update_data.append((row_number, 7, existing_total_qty))    # Column G
                update_data.append((row_number, 8, existing_remaining_qty))# Column H

                # Show debug before updating
                print(f"DEBUG - Current total_qty={existing_total_qty}, remaining_qty={existing_remaining_qty}")
                print(f"DEBUG - Update Data to Apply: {update_data}")

                # Perform all updates in Google Sheets
                for row_idx, col_idx, val in update_data:
                    sheet.update_cell(row_idx, col_idx, val)

                update_result = f"✅ Updated {update_id} successfully!"
                print(f"DEBUG - Successfully Updated {update_id}")

            except gspread.exceptions.CellNotFound:
                update_result = "⚠️ Error: Entry ID not found"
            except Exception as e:
                update_result = f"⚠️ Update error: {str(e)}"

        # 2) Handling new item additions
        elif 'input_text' in request.form:
            input_text = request.form["input_text"]
            parsed_entries = parse_input_with_deepseek(input_text)

            print("DEBUG - parsed_entries:", parsed_entries)

            # Grab existing data so we know how many rows exist
            records = sheet.get_all_records()
            row_count = len(records) + 1

            for entry in parsed_entries:
                if entry.get("errors"):
                    # If there are errors, skip or handle them differently
                    continue

                new_id = f"ITEM-{row_count}"
                row_count += 1

                # We add "catalogue number" in column C, but user hasn't specified it in the text parse
                # So let's just set it blank or you could parse it from the text if needed
                catalogue_number = ""

                # Our column references again:
                #   1=ID, 2=item, 3=catalogue_number, 4=storage_location, 5=box_label, 
                #   6=price, 7=total_qty, 8=remaining_qty, 9=date, 10=place_bought
                row_data = [
                    new_id,                  # Column A
                    entry["item"],          # Column B
                    catalogue_number,       # Column C
                    entry["storage_location"], # Column D
                    entry["box_label"],     # Column E
                    entry["price"],         # Column F
                    entry["total_qty"],     # Column G
                    entry.get("remaining_qty", ""), # Column H
                    entry["date"],          # Column I
                    entry["place_bought"]   # Column J
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
