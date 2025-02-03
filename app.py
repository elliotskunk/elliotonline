from flask import Flask, request, render_template
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from openai import OpenAI
from datetime import datetime
from rapidfuzz import process
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

# Open Google Sheet and worksheets
inventory_sheet = gsheet_client.open("DS ELLIOTONLINE").worksheet("Inventory")
sales_sheet = gsheet_client.open("DS ELLIOTONLINE").worksheet("Sales")
maintenance_sheet = gsheet_client.open("DS ELLIOTONLINE").worksheet("Maintenance")  # ✅ Define the maintenance sheet

# Fetch column data for validation
locations_list = maintenance_sheet.col_values(1)[1:]  # Skip header
box_labels_list = maintenance_sheet.col_values(2)[1:]  # Skip header
place_bought_list = maintenance_sheet.col_values(4)[1:]  # Skip header


app = Flask(__name__)

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
        audio_file = request.files.get('audio')

        if not audio_file:
            print("ERROR - No audio file received")
            return {"error": "No audio file received"}, 400  # Send error response

        filename = secure_filename(audio_file.filename)
        audio_file.save(filename)
        print(f"DEBUG - Saved file: {filename}")

        text = convert_speech_to_text(filename)
        print(f"DEBUG - Recognized Text: {text}")

        return {"recognized_text": text}  # Return JSON
    except Exception as e:
        print(f"ERROR - Exception in /upload: {str(e)}")
        return {"error": str(e)}, 500  # Return error response
    finally:
        if os.path.exists(filename):
            os.remove(filename)



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

            # Required: item
            item = entry.get('item')
            if not item:
                errors.append("Missing required field: item")

            # Price
            try:
                price = float(entry['price'])
            except (ValueError, TypeError, KeyError):
                errors.append("Invalid price format")
                price = 0.0

            # Total Qty
            try:
                total_qty = int(entry['total_qty'])
                if total_qty <= 0:
                    raise ValueError
            except (ValueError, TypeError, KeyError):
                errors.append("Invalid quantity format, defaulting to 1")
                total_qty = 1

            if total_qty == 1 and "Invalid quantity format, defaulting to 1" in errors:
                errors.remove("Invalid quantity format, defaulting to 1")

            # Remaining Qty defaults
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

        return parsed_entries

    except Exception as e:
        print(f"Parsing Error: {str(e)}")
        return [{'error': f"System error: {str(e)}", 'raw_entry': content}]



from rapidfuzz import process

def find_best_match(user_input, choices, threshold=80):
    """
    Find the closest matching item in the list using RapidFuzz.
    If no match meets the threshold, return the original user input.
    """
    print(f"DEBUG - Searching for: {user_input}")
    print(f"DEBUG - Available choices: {choices}")

    if not user_input or not choices:
        print("⚠️ No user input or no choices available.")
        return user_input  # Return original input if nothing to match against

    matches = process.extract(user_input, choices, limit=3, score_cutoff=threshold)
    print(f"DEBUG - Fuzzy Matches: {matches}")

    if not matches:
        print(f"⚠️ No good match found for '{user_input}'. Keeping original input.")
        return user_input  # No match found, return original input

    best_match = matches[0][0]  # Get best match
    confidence = matches[0][1]  # Get confidence score

    print(f"✅ Best match: {best_match} (Confidence: {confidence}%)")
    return best_match


@app.route('/process_voice_input', methods=['POST'])
def process_voice_input():
    data = request.json
    transcript = data.get("text", "")
    mode = data.get("mode", "general")

    if not transcript:
        return {"error": "No text received"}, 400

    print(f"🔍 Processing voice input for mode: {mode}")

    # Use AI to extract structured data with explicit field constraints
    response = deepseek_client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": f"""Extract relevant fields for mode '{mode}' and ensure they match values from the appropriate columns in the Maintenance sheet:
                - `update_item_name` must match an item in the Inventory Sheet.
                - `storage_location` must match one of these: {locations_list}
                - `box_label` must match one of these: {box_labels_list}
                - `place_bought` must match one of these: {place_bought_list}
                
                Return only JSON without any markdown formatting.
                """
            },
            {"role": "user", "content": transcript}
        ],
        temperature=0.3
    )

    # Debug: Print raw AI response
    raw_response = response.choices[0].message.content.strip()
    print(f"🛑 RAW AI RESPONSE: {raw_response}")

    # ✅ Strip markdown formatting (` ```json ... ``` `)
    if raw_response.startswith("```json"):
        raw_response = raw_response.split("```json")[1].split("```")[0].strip()

    try:
        extracted_data = json.loads(raw_response)
    except json.JSONDecodeError:
        print(f"⚠️ Failed to parse AI response as JSON: {raw_response}")
        extracted_data = {"error": "Failed to parse AI response"}

    print(f"📌 Extracted Data: {extracted_data}")

    # ✅ Apply manual fuzzy matching for locations, box labels, and place bought
    # ✅ Use fuzzy matching to ensure correct values from the Maintenance Sheet
    if "storage_location" in extracted_data:
        extracted_data["storage_location"] = find_best_match(extracted_data["storage_location"], locations_list)

    if "box_label" in extracted_data:
        extracted_data["box_label"] = find_best_match(extracted_data["box_label"], box_labels_list)

    if "place_bought" in extracted_data:
        extracted_data["place_bought"] = find_best_match(extracted_data["place_bought"], place_bought_list)


    print(f"📌 Matched Data: {extracted_data}")

    return extracted_data







@app.route("/", methods=["GET", "POST"])
def home():
    processed_entries = []
    update_result = None

    if request.method == "POST":
        form_keys = request.form.keys()

        # --- 1) Adding a NEW item ---
        if 'input_text' in form_keys:
            input_text = request.form["input_text"]
            parsed_entries = parse_input_with_deepseek(input_text)
            print("DEBUG - parsed_entries:", parsed_entries)

            records = inventory_sheet.get_all_records()
            row_count = len(records) + 1

            for entry in parsed_entries:
                if entry.get("errors"):
                    continue

                new_id = f"ITEM-{row_count}"
                row_count += 1

                row_data = [
                    new_id,
                    entry["item"],
                    "",
                    entry["storage_location"],
                    entry["box_label"],
                    entry["price"],
                    entry["total_qty"],
                    entry.get("remaining_qty", ""),
                    entry["date"],
                    entry["place_bought"]
                ]
                inventory_sheet.append_row(row_data)
                entry["id"] = new_id
                processed_entries.append(entry)

        # --- 2) Updating an existing Inventory entry (by ID or by name) ---
        elif 'update_id' in form_keys or 'update_item_name' in form_keys:
            try:
                update_id = request.form.get('update_id', '').strip()
                update_item_name = request.form.get('update_item_name', '').strip()

                # 🔍 **Find entry by ID or Name**
                if update_id:
                    print(f"DEBUG - Searching by ID: {update_id}")
                    cell = inventory_sheet.find(update_id)  
                elif update_item_name:
                    print(f"DEBUG - Searching for closest match to '{update_item_name}'...")
                    all_items = inventory_sheet.col_values(2)[1:]  # Ignore header row
                    best_match, multiple_matches = find_best_match(update_item_name, all_items)

                    if not best_match and multiple_matches:
                        update_result = f"⚠️ Multiple matches found: {', '.join(multiple_matches)}. Please refine your search."
                        return render_template("index.html", entries=processed_entries, update_result=update_result)

                    if not best_match:
                        update_result = f"⚠️ No matching items found for '{update_item_name}'."
                        return render_template("index.html", entries=processed_entries, update_result=update_result)

                    cell = inventory_sheet.find(best_match, in_column=2)

                if not cell:
                    raise ValueError(f"⚠️ Error: Item '{update_item_name}' not found")

                row_number = cell.row
                row_values = inventory_sheet.row_values(row_number)
                while len(row_values) < 10:
                    row_values.append("")

                # Fetch existing values
                existing_catalogue, existing_storage_location, existing_box_label = row_values[2:5]
                existing_price, existing_total_qty, existing_remaining_qty = row_values[5:8]
                existing_place_bought = row_values[9]

                try:
                    existing_total_qty = int(existing_total_qty)
                except ValueError:
                    existing_total_qty = 1

                try:
                    existing_remaining_qty = int(existing_remaining_qty)
                except ValueError:
                    existing_remaining_qty = existing_total_qty

                # Capture new input values
                new_values = {
                    "catalogue_number": request.form.get('catalogue_number', '').strip(),
                    "storage_location": request.form.get('storage_location', '').strip(),
                    "box_label": request.form.get('box_label', '').strip(),
                    "place_bought": request.form.get('place_bought', '').strip(),
                    "restock_qty": request.form.get('restock_qty', '').strip(),
                    "quantity_sold": request.form.get('quantity_sold', '').strip()
                }

                update_data = []

                # Update values if provided
                for col_index, key, existing_value in [
                    (3, "catalogue_number", existing_catalogue),
                    (4, "storage_location", existing_storage_location),
                    (5, "box_label", existing_box_label),
                    (10, "place_bought", existing_place_bought)
                ]:
                    if new_values[key]:
                        update_data.append((row_number, col_index, new_values[key]))
                    else:
                        new_values[key] = existing_value

                # Process restocking
                # --- Processing restocking ---
                if new_values["restock_qty"]:
                    try:
                        restock_qty = int(new_values["restock_qty"])
                        if restock_qty > 0:
                            existing_total_qty += restock_qty
                            existing_remaining_qty += restock_qty

                            # Fetch existing restock history (column index: adjust as per your sheet structure)
                            restock_history_col = 11  # Assuming column 11 stores restock history
                            existing_restock_history = inventory_sheet.cell(row_number, restock_history_col).value or ""

                            # Append new restock entry
                            restock_entry = f"{datetime.now().strftime('%d/%m/%Y')} (x{restock_qty})"
                            if existing_restock_history.strip():  # Ensure we don't append unnecessary commas
                                updated_restock_history = f"{existing_restock_history}, {restock_entry}"
                            else:
                                updated_restock_history = restock_entry

                            # ✅ Ensure update_data only stores valid key-value pairs
                            update_data.append((row_number, restock_history_col, updated_restock_history))  # ✅ Correct format

                    except ValueError:
                        print("⚠️ Invalid restock quantity. Ignoring restock update.")



                # Process sale
                if new_values["quantity_sold"]:
                    try:
                        quantity_sold = int(new_values["quantity_sold"])
                        existing_remaining_qty -= quantity_sold
                        existing_remaining_qty = max(0, existing_remaining_qty)
                    except ValueError:
                        pass

                update_data.append((row_number, 7, existing_total_qty))  
                update_data.append((row_number, 8, existing_remaining_qty))

                # Apply updates
                for row_idx, col_idx, val in update_data:
                    inventory_sheet.update_cell(row_idx, col_idx, val)

                update_label = update_id if update_id else update_item_name
                update_result = f"✅ Updated {update_label} successfully!"

            except gspread.exceptions.APIError:
                update_result = "⚠️ Google Sheets API error."
            except ValueError as e:
                update_result = f"⚠️ {str(e)}"
            except Exception as e:
                update_result = f"⚠️ Unexpected error: {str(e)}"

        # --- 3) LOGGING A SALE ---
        elif 'sales_item' in form_keys:
            try:
                sales_item_name = request.form.get('sales_item', '').strip()
                quantity_sold = request.form.get('quantity_sold', '1').strip()
                sold_price = request.form.get('sold_price', '').strip()
                date_sold = request.form.get('date_sold', '').strip() or datetime.now().strftime("%d/%m/%Y")
                buyer = request.form.get('buyer', '').strip()

                try:
                    quantity_sold = int(quantity_sold)
                except ValueError:
                    quantity_sold = 1

                try:
                    sold_price = float(sold_price)
                except ValueError:
                    sold_price = 0.0

                # Find best match
                all_items = inventory_sheet.col_values(2)[1:]
                best_match, multiple_matches = find_best_match(sales_item_name, all_items)

                if not best_match:
                    update_result = f"⚠️ No matching items found for '{sales_item_name}'."
                    return render_template("index.html", entries=processed_entries, update_result=update_result)

                item_row = next((i + 1 for i, row in enumerate(inventory_sheet.get_all_values()) if row[1] == best_match), None)
                if not item_row:
                    raise ValueError(f"⚠️ '{best_match}' matched but not found.")

                existing_remaining = int(inventory_sheet.cell(item_row, 8).value or 0)
                if existing_remaining < quantity_sold:
                    raise ValueError(f"⚠️ Not enough stock for {quantity_sold} of '{best_match}'.")

                inventory_sheet.update_cell(item_row, 8, existing_remaining - quantity_sold)

                sale_id = f"{best_match.replace(' ', '_')}-{datetime.now().strftime('%d%m')}-{buyer.replace(' ', '_')}"
                sales_data = [sale_id, best_match, quantity_sold, sold_price, date_sold, buyer, existing_remaining - quantity_sold]
                sales_sheet.append_row(sales_data)

                update_result = f"✅ Sold {quantity_sold}x '{best_match}' to {buyer}. Remaining: {existing_remaining - quantity_sold}"

            except ValueError as e:
                update_result = f"⚠️ {str(e)}"
            except Exception as e:
                update_result = f"⚠️ Sales error: {str(e)}"

    return render_template("index.html", entries=processed_entries, update_result=update_result)



if __name__ == "__main__":
    print("Starting up the eBay Inventory Manager...")
    app.run(debug=True)
