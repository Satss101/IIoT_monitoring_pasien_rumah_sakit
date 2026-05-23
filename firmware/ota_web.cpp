#include "ota_web.h"

/* ================================
   WEB SERVER OBJECT
================================ */
WebServer server(80);
bool isAuthenticated = false;

/* ================================
   HTML UI - LOGIN PAGE
================================ */
const char loginPage[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESP32 OTA Login</title>

<style>
body {
    margin:0;
    font-family: Arial;
    background: linear-gradient(135deg,#0f2027,#203a43,#2c5364);
    height:100vh;
    display:flex;
    justify-content:center;
    align-items:center;
    color:white;
}

.card {
    background: rgba(255,255,255,0.1);
    padding:30px;
    border-radius:15px;
    backdrop-filter: blur(10px);
    width:300px;
    text-align:center;
    box-shadow:0 0 20px rgba(0,0,0,0.5);
}

input {
    width:100%;
    padding:10px;
    margin:10px 0;
    border:none;
    border-radius:8px;
}

button {
    width:100%;
    padding:10px;
    border:none;
    border-radius:8px;
    background:#00c6ff;
    color:white;
    font-weight:bold;
    cursor:pointer;
}

button:hover {
    background:#0072ff;
}
</style>

</head>

<body>

<div class="card">
<h2>ESP32 OTA SYSTEM</h2>

<form action="/login" method="POST">
<input type="text" name="user" placeholder="Username">
<input type="password" name="pass" placeholder="Password">
<button type="submit">LOGIN</button>
</form>

</div>

</body>
</html>

)rawliteral";

/* ================================
   HTML UI - DASHBOARD OTA
================================ */
const char uploadPage[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OTA Dashboard</title>

<style>
body {
    margin:0;
    font-family: Arial;
    background: linear-gradient(135deg,#141e30,#243b55);
    color:white;
    display:flex;
    justify-content:center;
    align-items:center;
    height:100vh;
}

.card {
    background: rgba(255,255,255,0.08);
    padding:30px;
    border-radius:15px;
    width:350px;
    text-align:center;
    backdrop-filter: blur(10px);
}

input[type=file] {
    margin:20px 0;
    color:white;
}

button {
    width:100%;
    padding:10px;
    border:none;
    border-radius:8px;
    background:#00c853;
    color:white;
    font-weight:bold;
    cursor:pointer;
}

button:hover {
    background:#00e676;
}

.bar {
    width:100%;
    height:10px;
    background:#333;
    border-radius:5px;
    margin-top:10px;
}

.progress {
    height:10px;
    width:0%;
    background:#00e676;
    border-radius:5px;
}
</style>

</head>

<body>

<div class="card">

<h2>Firmware Upload</h2>

<form method="POST" action="/update" enctype="multipart/form-data">
<input type="file" name="update" required>
<button type="submit">UPLOAD FIRMWARE</button>
</form>

<div class="bar">
<div class="progress" id="progress"></div>
</div>

<p id="status">Ready</p>

</div>

<script>
const form = document.querySelector("form");
const progress = document.getElementById("progress");
const status = document.getElementById("status");

form.onsubmit = function(e){
    status.innerHTML = "Uploading...";
};
</script>

</body>
</html>

)rawliteral";

/* ================================
   LOGIN HANDLER
================================ */
void handleLogin()
{
    String user = server.arg("user");
    String pass = server.arg("pass");

    if(user == OTA_USER && pass == OTA_PASS)
    {
        isAuthenticated = true;
        server.sendHeader("Location","/upload");
        server.send(302,"text/plain","");
    }
    else
    {
        server.send(200,"text/html","Login Failed");
    }
}

/* ================================
   LOGIN PAGE
================================ */
void handleLoginPage()
{
    server.send(200,"text/html",loginPage);
}

/* ================================
   UPLOAD PAGE
================================ */
void handleUploadPage()
{
    if(!isAuthenticated)
    {
        server.sendHeader("Location","/");
        server.send(302,"text/plain","");
        return;
    }

    server.send(200,"text/html",uploadPage);
}

/* ================================
   OTA FIRMWARE UPLOAD
================================ */
void handleFirmwareUpload()
{
    if(!isAuthenticated)
    {
        server.send(403,"text/plain","Not Authorized");
        return;
    }

    HTTPUpload& upload = server.upload();

    if(upload.status == UPLOAD_FILE_START)
    {
        Serial.printf("Update Start: %s\n", upload.filename.c_str());
        Update.begin(UPDATE_SIZE_UNKNOWN);
    }

    else if(upload.status == UPLOAD_FILE_WRITE)
    {
        Update.write(upload.buf, upload.currentSize);
    }

    else if(upload.status == UPLOAD_FILE_END)
    {
        if(Update.end(true))
        {
            Serial.println("Update Success");
            server.sendHeader("Location","/");
            server.send(302,"text/plain","Success");
            ESP.restart();
        }
        else
        {
            Serial.println("Update Failed");
            server.send(500,"text/plain","Update Failed");
        }
    }
}

/* ================================
   NOT FOUND
================================ */
void handleNotFound()
{
    server.send(404,"text/plain","404 Not Found");
}

/* ================================
   SETUP OTA
================================ */
void setupOTA()
{
    server.on("/", handleLoginPage);
    server.on("/login", HTTP_POST, handleLogin);
    server.on("/upload", handleUploadPage);
    server.on("/update", HTTP_POST,
        [](){ server.send(200); },
        handleFirmwareUpload
    );

    server.onNotFound(handleNotFound);

    server.begin();

    Serial.println("OTA Web Server Started");
}



/* ================================
   LOOP OTA
================================ */

void handleOTA()
{
    server.handleClient();
}