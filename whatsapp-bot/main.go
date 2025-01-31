package main

import (
	"context"
	"fmt"
	"log"
	"time"

	"go.mau.fi/whatsmeow"
	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"

	_ "github.com/mattn/go-sqlite3" // SQLite driver
)

// CustomLogger implements waLog.Logger
type CustomLogger struct{}

var _ waLog.Logger = (*CustomLogger)(nil)

func (c *CustomLogger) Debugf(format string, args ...interface{}) {
	fmt.Printf("[DEBUG] "+format+"\n", args...)
}

func (c *CustomLogger) Infof(format string, args ...interface{}) {
	fmt.Printf("[INFO] "+format+"\n", args...)
}

func (c *CustomLogger) Warnf(format string, args ...interface{}) {
	fmt.Printf("[WARN] "+format+"\n", args...)
}

func (c *CustomLogger) Errorf(format string, args ...interface{}) {
	fmt.Printf("[ERROR] "+format+"\n", args...)
}

func (c *CustomLogger) Sub(module string) waLog.Logger {
	return c // for simplicity
}

// Helper: convert string to *string for proto
func strPtr(s string) *string {
	return &s
}

func eventHandler(evt interface{}) {
	switch v := evt.(type) {
	case *events.Message:
		message := v.Message.GetConversation()
		senderJID := v.Info.Sender
		fmt.Printf("Incoming message from %s: %s\n", senderJID.User, message)
	default:
		// handle other events as needed
	}
}

func main() {
	dbLog := &CustomLogger{}

	// Create the SQL store
	container, err := sqlstore.New("sqlite3", "file:session.db?_foreign_keys=on", dbLog)
	if err != nil {
		log.Fatalf("Database error: %v", err)
	}

	deviceStore, err := container.GetFirstDevice()
	if err != nil {
		log.Fatalf("Device store error: %v", err)
	}

	// Create a new client
	client := whatsmeow.NewClient(deviceStore, dbLog)
	client.AddEventHandler(eventHandler)

	if client.Store.ID == nil {
		// Need to scan QR
		qrChan, _ := client.GetQRChannel(context.Background())
		err = client.Connect()
		if err != nil {
			log.Fatalf("Failed to connect: %v", err)
		}

		fmt.Println("Scan the QR code below:")
		for evt := range qrChan {
			if evt.Event == "code" {
				fmt.Printf("QR Code: %s\n", evt.Code)
			} else {
				fmt.Printf("QR Event: %s\n", evt.Event)
			}
		}
	} else {
		// Already authenticated, just connect
		err = client.Connect()
		if err != nil {
			log.Fatalf("Failed to connect: %v", err)
		}
	}

	// Send a test message after 5 seconds
	go func() {
		time.Sleep(5 * time.Second)

		testJID, err := types.ParseJID("447808025786@s.whatsapp.net")
		if err != nil {
			log.Printf("Invalid JID: %v", err)
			return
		}

		msg := &waProto.Message{
			Conversation: strPtr("Hello from the updated WhatsMeow bot!"),
		}

		// 4th argument is the optional SendRequestExtra
		sendResp, err := client.SendMessage(context.Background(), testJID, msg, whatsmeow.SendRequestExtra{})
		if err != nil {
			log.Printf("Send message error: %v", err)
		} else {
			log.Printf("Message sent; server timestamp: %v", sendResp.Timestamp)
		}
	}()

	// Keep running
	select {}
}
