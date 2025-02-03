function startVoiceRecognition(callback) {
    console.log("🎤 Starting voice recognition...");

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        alert("❌ Your browser does not support voice recognition.");
        return;
    }

    let recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-GB";

    recognition.start();

    recognition.onresult = function (event) {
        let transcript = event.results[0][0].transcript;
        console.log("✅ Recognized Text:", transcript);
        alert("🎙 Recognized: " + transcript);
        callback(transcript);
    };

    recognition.onerror = function (event) {
        console.error("❌ Speech recognition error:", event.error);
        alert("Speech recognition error: " + event.error);
    };

    recognition.onend = function () {
        console.log("🛑 Speech recognition stopped.");
    };
}

// 🎤 New Entry Button
function recordNewEntry() {
    startVoiceRecognition(function (transcript) {
        let inputField = document.querySelector("textarea[name='input_text']");
        if (inputField) {
            inputField.value += (inputField.value ? " " : "") + transcript;
        }
    });
}

// 🎤 Update Entry Button (APPENDS to existing inputs)
function recordUpdateEntry() {
    startVoiceRecognition(function (transcript) {
        fetch('/process_voice_input', {
            method: 'POST',
            body: JSON.stringify({ text: transcript, mode: "update" }),
            headers: { 'Content-Type': 'application/json' }
        })
        .then(response => response.json())
        .then(data => {
            console.log("📌 AI Processed Update Data:", data);

            // Append to existing values
            document.querySelector("[name='update_id']").value += (data.update_id ? " " + data.update_id : "");
            document.querySelector("[name='update_item_name']").value += (data.update_item_name ? " " + data.update_item_name : "");
            document.querySelector("[name='catalogue_number']").value += (data.catalogue_number ? " " + data.catalogue_number : "");
            document.querySelector("[name='storage_location']").value += (data.storage_location ? " " + data.storage_location : "");
            document.querySelector("[name='box_label']").value += (data.box_label ? " " + data.box_label : "");
            document.querySelector("[name='place_bought']").value += (data.place_bought ? " " + data.place_bought : "");
            document.querySelector("[name='restock_qty']").value += (data.restock_qty ? " " + data.restock_qty : "");
            document.querySelector("[name='quantity_sold']").value += (data.quantity_sold ? " " + data.quantity_sold : "");
        })
        .catch(error => console.error("⚠️ ERROR - Processing voice input:", error));
    });
}

// 🎤 Log Sale Button (APPENDS to existing inputs)
function recordSale() {
    startVoiceRecognition(function (transcript) {
        fetch('/process_voice_input', {
            method: 'POST',
            body: JSON.stringify({ text: transcript, mode: "sale" }),
            headers: { 'Content-Type': 'application/json' }
        })
        .then(response => response.json())
        .then(data => {
            console.log("📌 AI Processed Sale Data:", data);

            // Append to existing values
            document.querySelector("[name='sales_item']").value += (data.sales_item ? " " + data.sales_item : "");
            document.querySelector("[name='quantity_sold']").value += (data.quantity_sold ? " " + data.quantity_sold : "");
            document.querySelector("[name='sold_price']").value += (data.sold_price ? " " + data.sold_price : "");
            document.querySelector("[name='buyer']").value += (data.buyer ? " " + data.buyer : "");
            document.querySelector("[name='date_sold']").value += (data.date_sold ? " " + data.date_sold : "");
        })
        .catch(error => console.error("⚠️ ERROR - Processing voice input:", error));
    });
}
