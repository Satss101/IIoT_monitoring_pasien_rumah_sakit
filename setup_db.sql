-- ============================================================
-- BNSP IoT Monitoring System - Database Setup
-- Jalankan: mysql -u root -p < setup_db.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS bnsp_iot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE bnsp_iot;

-- Tabel monitoring
CREATE TABLE IF NOT EXISTS monitoring (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    temp      FLOAT          COMMENT 'Suhu (°C)',
    hum       FLOAT          COMMENT 'Kelembapan (%)',
    spo2      FLOAT          COMMENT 'Saturasi Oksigen (%)',
    hr        FLOAT          COMMENT 'Detak Jantung (bpm)',
    gsr       FLOAT          COMMENT 'Galvanic Skin Response',
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Tabel setting
CREATE TABLE IF NOT EXISTS setting (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    threshold FLOAT NOT NULL DEFAULT 95.0 COMMENT 'Ambang batas SpO2 (%)'
) ENGINE=InnoDB;

-- Seed default threshold
INSERT INTO setting (threshold) SELECT 95.0 WHERE NOT EXISTS (SELECT 1 FROM setting);

SELECT 'Database bnsp_iot berhasil dibuat!' AS status;
