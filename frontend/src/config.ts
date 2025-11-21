export const API_HTTP_URL = import.meta.env.VITE_API_HTTP_URL || "http://localhost:8000";
//export const API_HTTP_URL = import.meta.env.VITE_API_HTTP_URL || "http://localhost:8000";
export const API_WS_URL = import.meta.env.VITE_API_WS_URL || `${API_HTTP_URL.replace(/^https?/, (match) => match === "https" ? "wss" : "ws")}/ws/chat`;

export const GROQ_API_KEY = import.meta.env.VITE_GROQ_API_KEY || "YOUR_API_KEY_HERE";

export const getMemberId = () => {
  // HARDCODED FOR TESTING - REMOVE AFTER
   return '1f02a411-c793-603b-9438-d7da75fe04e1';
  
  // const stored = localStorage.getItem('staffId');
  // if (!stored) return '';
  
  // // Handle case where staffId might be stored as JSON string
  // try {
  //   const parsed = JSON.parse(stored);
  //   return typeof parsed === 'string' ? parsed.trim() : String(parsed).trim();
  // } catch {
  //   // If not JSON, return as-is
  //   return stored.trim();
  // }
};

export const getBusinessId = () => {
  // HARDCODED FOR TESTING - REMOVE AFTER
   return '1ef944db-0e37-6f01-943a-214dd19f54e9';
  
  // // First, try the bDetails key (for backward compatibility)
  // const raw = localStorage.getItem('bDetails');
  // if (raw) {
  //   try {
  //     const parsedData = JSON.parse(raw);
  //     if (parsedData && typeof parsedData === 'object' && parsedData.id) {
  //       return String(parsedData.id).trim();
  //     }
  //     if (typeof parsedData === 'string' && parsedData.trim()) {
  //       return parsedData.trim();
  //     }
  //   } catch {
  //     // If parsing fails, treat as string
  //     if (typeof raw === 'string' && raw.trim()) {
  //       return raw.trim();
  //     }
  //   }
  // }

  // // If bDetails doesn't exist, look for business details stored under UUID key
  // // Business details are stored with the business ID as the key
  // const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  
  // for (let i = 0; i < localStorage.length; i++) {
  //   const key = localStorage.key(i);
  //   if (!key) continue;
    
  //   // Check if key matches UUID pattern (likely a business ID)
  //   if (uuidPattern.test(key)) {
  //     try {
  //       const value = localStorage.getItem(key);
  //       if (value) {
  //         const parsed = JSON.parse(value);
  //         // Check if this looks like a business object (has id field matching the key)
  //         if (parsed && typeof parsed === 'object' && parsed.id === key) {
  //           return String(parsed.id).trim();
  //         }
  //       }
  //     } catch {
  //       // Continue searching if this key doesn't contain valid JSON
  //       continue;
  //     }
  //   }
  // }

  // return '';
};

export const getStaffType = () => {
  return localStorage.getItem('staffType') || import.meta.env.VITE_STAFF_TYPE || '';
};

export const getStaffName = () => {
  return localStorage.getItem('staffName') || import.meta.env.VITE_STAFF_NAME || '';
};

export const getBusinessDetails = () => {
  // First, try the bDetails key (for backward compatibility)
  const fromStorage = localStorage.getItem('bDetails');
  if (fromStorage) {
    try {
      return JSON.parse(fromStorage);
    } catch {
      return { id: fromStorage };
    }
  }

  // If bDetails doesn't exist, look for business details stored under UUID key
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key) continue;
    
    // Check if key matches UUID pattern (likely a business ID)
    if (uuidPattern.test(key)) {
      try {
        const value = localStorage.getItem(key);
        if (value) {
          const parsed = JSON.parse(value);
          // Check if this looks like a business object (has id field matching the key)
          if (parsed && typeof parsed === 'object' && parsed.id === key) {
            return parsed;
          }
        }
      } catch {
        // Continue searching if this key doesn't contain valid JSON
        continue;
      }
    }
  }

  return null;
};
