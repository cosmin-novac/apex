/**
 * Trade Republic Connector - IndexedDB Storage & API Integration
 * Handles secure storage of TR credentials and portfolio data in browser IndexedDB
 */

const DB_NAME = 'TradeRepublicVault';
const DB_VERSION = 1;
const STORE_NAME = 'portfolio_data';
const CRED_STORE = 'credentials';

// Initialize IndexedDB
function initDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);
        
        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            
            // Store for portfolio data
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME, { keyPath: 'id' });
            }
            
            // Store for encrypted credentials
            if (!db.objectStoreNames.contains(CRED_STORE)) {
                db.createObjectStore(CRED_STORE, { keyPath: 'id' });
            }
        };
    });
}

// Encrypt data using Web Crypto API
async function encryptData(data, pin) {
    const encoder = new TextEncoder();
    const dataBuffer = encoder.encode(JSON.stringify(data));
    
    // Derive key from PIN
    const keyMaterial = await crypto.subtle.importKey(
        'raw',
        encoder.encode(pin),
        { name: 'PBKDF2' },
        false,
        ['deriveBits', 'deriveKey']
    );
    
    const salt = crypto.getRandomValues(new Uint8Array(16));
    const key = await crypto.subtle.deriveKey(
        {
            name: 'PBKDF2',
            salt: salt,
            iterations: 100000,
            hash: 'SHA-256'
        },
        keyMaterial,
        { name: 'AES-GCM', length: 256 },
        false,
        ['encrypt']
    );
    
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const encrypted = await crypto.subtle.encrypt(
        { name: 'AES-GCM', iv: iv },
        key,
        dataBuffer
    );
    
    return {
        encrypted: Array.from(new Uint8Array(encrypted)),
        iv: Array.from(iv),
        salt: Array.from(salt)
    };
}

// Decrypt data using Web Crypto API
async function decryptData(encryptedObj, pin) {
    const encoder = new TextEncoder();
    const decoder = new TextDecoder();
    
    const keyMaterial = await crypto.subtle.importKey(
        'raw',
        encoder.encode(pin),
        { name: 'PBKDF2' },
        false,
        ['deriveBits', 'deriveKey']
    );
    
    const key = await crypto.subtle.deriveKey(
        {
            name: 'PBKDF2',
            salt: new Uint8Array(encryptedObj.salt),
            iterations: 100000,
            hash: 'SHA-256'
        },
        keyMaterial,
        { name: 'AES-GCM', length: 256 },
        false,
        ['decrypt']
    );
    
    const decrypted = await crypto.subtle.decrypt(
        { name: 'AES-GCM', iv: new Uint8Array(encryptedObj.iv) },
        key,
        new Uint8Array(encryptedObj.encrypted)
    );
    
    return JSON.parse(decoder.decode(decrypted));
}

// Save portfolio data to IndexedDB (encrypted)
async function savePortfolioData(data, pin) {
    try {
        const db = await initDB();
        const encrypted = await encryptData(data, pin);
        
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE_NAME, 'readwrite');
            const store = tx.objectStore(STORE_NAME);
            
            const record = {
                id: 'portfolio',
                data: encrypted,
                timestamp: new Date().toISOString()
            };
            
            const request = store.put(record);
            request.onsuccess = () => resolve(true);
            request.onerror = () => reject(request.error);
        });
    } catch (error) {
        console.error('Error saving portfolio data:', error);
        return false;
    }
}

// Load portfolio data from IndexedDB
async function loadPortfolioData(pin) {
    try {
        const db = await initDB();
        
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE_NAME, 'readonly');
            const store = tx.objectStore(STORE_NAME);
            const request = store.get('portfolio');
            
            request.onsuccess = async () => {
                if (request.result && request.result.data) {
                    try {
                        const decrypted = await decryptData(request.result.data, pin);
                        resolve({
                            data: decrypted,
                            timestamp: request.result.timestamp
                        });
                    } catch (e) {
                        resolve({ error: 'Invalid PIN or corrupted data' });
                    }
                } else {
                    resolve(null);
                }
            };
            request.onerror = () => reject(request.error);
        });
    } catch (error) {
        console.error('Error loading portfolio data:', error);
        return null;
    }
}

// Check if portfolio data exists
async function hasStoredData() {
    try {
        const db = await initDB();
        
        return new Promise((resolve) => {
            const tx = db.transaction(STORE_NAME, 'readonly');
            const store = tx.objectStore(STORE_NAME);
            const request = store.get('portfolio');
            
            request.onsuccess = () => resolve(!!request.result);
            request.onerror = () => resolve(false);
        });
    } catch {
        return false;
    }
}

// Clear all stored data
async function clearStoredData() {
    try {
        const db = await initDB();
        
        return new Promise((resolve, reject) => {
            const tx = db.transaction([STORE_NAME, CRED_STORE], 'readwrite');
            tx.objectStore(STORE_NAME).clear();
            tx.objectStore(CRED_STORE).clear();
            
            tx.oncomplete = () => resolve(true);
            tx.onerror = () => reject(tx.error);
        });
    } catch (error) {
        console.error('Error clearing data:', error);
        return false;
    }
}

// Save session token (encrypted)
async function saveSessionToken(phoneNumber, token, pin) {
    try {
        const db = await initDB();
        const encrypted = await encryptData({ phoneNumber, token }, pin);
        
        return new Promise((resolve, reject) => {
            const tx = db.transaction(CRED_STORE, 'readwrite');
            const store = tx.objectStore(CRED_STORE);
            
            const record = {
                id: 'session',
                data: encrypted,
                timestamp: new Date().toISOString()
            };
            
            const request = store.put(record);
            request.onsuccess = () => resolve(true);
            request.onerror = () => reject(request.error);
        });
    } catch (error) {
        console.error('Error saving session:', error);
        return false;
    }
}

// Get session token
async function getSessionToken(pin) {
    try {
        const db = await initDB();
        
        return new Promise((resolve, reject) => {
            const tx = db.transaction(CRED_STORE, 'readonly');
            const store = tx.objectStore(CRED_STORE);
            const request = store.get('session');
            
            request.onsuccess = async () => {
                if (request.result && request.result.data) {
                    try {
                        const decrypted = await decryptData(request.result.data, pin);
                        resolve(decrypted);
                    } catch (e) {
                        resolve(null);
                    }
                } else {
                    resolve(null);
                }
            };
            request.onerror = () => reject(request.error);
        });
    } catch (error) {
        return null;
    }
}

// Expose functions to Dash via window object
window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.trConnector = {
    
    // Check for existing data
    checkStoredData: async function(trigger) {
        const hasData = await hasStoredData();
        return JSON.stringify({ hasData: hasData });
    },
    
    // Save portfolio data
    saveData: async function(data, pin) {
        if (!data || !pin) return JSON.stringify({ success: false, error: 'Missing data or PIN' });
        
        try {
            const portfolioData = JSON.parse(data);
            const success = await savePortfolioData(portfolioData, pin);
            return JSON.stringify({ success: success });
        } catch (error) {
            return JSON.stringify({ success: false, error: error.message });
        }
    },
    
    // Load portfolio data with PIN
    loadData: async function(pin, trigger) {
        if (!pin) return JSON.stringify({ success: false, error: 'PIN required' });
        
        try {
            const result = await loadPortfolioData(pin);
            if (result && result.error) {
                return JSON.stringify({ success: false, error: result.error });
            }
            if (result && result.data) {
                return JSON.stringify({ 
                    success: true, 
                    data: result.data, 
                    timestamp: result.timestamp 
                });
            }
            return JSON.stringify({ success: false, error: 'No data found' });
        } catch (error) {
            return JSON.stringify({ success: false, error: error.message });
        }
    },
    
    // Clear all data
    clearData: async function(trigger) {
        const success = await clearStoredData();
        return JSON.stringify({ success: success });
    },
    
    // Save Trade Republic session
    saveSession: async function(phoneNumber, token, pin) {
        if (!phoneNumber || !token || !pin) {
            return JSON.stringify({ success: false, error: 'Missing credentials' });
        }
        
        const success = await saveSessionToken(phoneNumber, token, pin);
        return JSON.stringify({ success: success });
    },
    
    // Get Trade Republic session
    getSession: async function(pin, trigger) {
        if (!pin) return JSON.stringify({ success: false, error: 'PIN required' });
        
        try {
            const session = await getSessionToken(pin);
            if (session) {
                return JSON.stringify({ success: true, session: session });
            }
            return JSON.stringify({ success: false, error: 'No session found' });
        } catch (error) {
            return JSON.stringify({ success: false, error: error.message });
        }
    }
};

// Initialize DB on load
initDB().then(() => {
    console.log('TradeRepublic IndexedDB initialized');
}).catch(console.error);
