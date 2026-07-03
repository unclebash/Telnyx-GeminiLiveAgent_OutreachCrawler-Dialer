-- Database schema for standalone Maps Fundraiser tool

CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    place_id TEXT UNIQUE,
    address TEXT,
    phone TEXT,
    website TEXT,
    rating REAL,
    user_ratings_total INTEGER,
    status TEXT DEFAULT 'Pending', -- 'Pending', 'Called', 'Email Sent', 'Donated', 'Denied'
    email TEXT, -- Extracted via crawler
    intro_email_sent INTEGER DEFAULT 0, -- 0 = No, 1 = Yes
    notes TEXT
);

CREATE TABLE IF NOT EXISTS outbound_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER,
    outcome TEXT NOT NULL, -- 'busy/no_answer', 'donated', 'denied', 'referred'
    notes TEXT,
    called_at TEXT DEFAULT CURRENT_TIMESTAMP,
    caller_name TEXT,
    FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_org_id INTEGER,
    contact_name TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    status TEXT DEFAULT 'Pending', -- 'Pending', 'Contacted', 'Denied', 'Donated'
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(original_org_id) REFERENCES organizations(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value TEXT
);

