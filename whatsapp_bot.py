import pywhatkit as kit
import time
from datetime import datetime
import os
from flask import Flask, request
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Initialize DeepSeek client
deepseek_client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://api.deepseek.com"
)

# Google Sheets setup
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
gsheet_client = gspread.authorize(creds)
sheet = gsheet_client.open("DS ELLIOTONLINE").worksheet("Inventory")

# WhatsApp bot function
def whatsapp_bot():
    print("Waiting for messages...")
    
    while True:
        try:
            # Check for new messages (you can customize this logic)
            # For now, we'll simulate receiving a message
            message = input("Enter a message (or 'exit' to quit): ")
            if message.lower() == "exit":
                break
            
            # Process the message using your existing DeepSeek function
            parsed_entries = parse_input_with_deepseek(message)
            
            # Update Google Sheets
            for entry in parsed_entries:
                if entry.get('errors'):
                    print(f"Error: {entry['errors']}")
                    continue
                
                row = [
                    entry['item'],
                    entry['price'],
                    entry['date'],
                    entry.get('storage_location', ''),
                    entry.get('box_label', ''),
                    entry['total_qty'],
                    entry['place_bought'],
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ]
                
                try:
                    sheet.append_row(row)
                    print(f"Added: {entry['item']} (£{entry['price']})")
                except Exception as e:
                    print(f"Failed to add {entry['item']}: {str(e)}")
        
        except Exception as e:
            print(f"Error: {str(e)}")
            break

# Your existing DeepSeek parsing function
def parse_input_with_deepseek(text):
    """Parse inventory input using DeepSeek API"""
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
        return [{'error': f"System error: {str(e)}"}]

# Run the bot
if __name__ == "__main__":
    whatsapp_bot()