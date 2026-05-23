#ifndef OTA_WEB_H
#define OTA_WEB_H

#include <WebServer.h>
#include <Update.h>
#include <WiFi.h>

/* ================================
   LOGIN CREDENTIAL (SIMPLE MODE)
================================ */
#define OTA_USER "admin"
#define OTA_PASS "admin"

/* ================================
   WEB SERVER
================================ */
extern WebServer server;

/* ================================
   OTA FUNCTION
================================ */
// Inisialisasi OTA Web Server
void setupOTA();
// Loop handler OTA (wajib dipanggil di loop utama)
void handleOTA();

/* ================================
   INTERNAL HANDLER
================================ */
void handleLoginPage();
void handleLogin();
void handleUploadPage();
void handleFirmwareUpload();
void handleNotFound();

#endif