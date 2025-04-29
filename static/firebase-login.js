// -------------------- Firebase Imports --------------------
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-app.js";
import {
  getAuth,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  onAuthStateChanged,
  signOut,
  getIdToken,
  setPersistence,
  browserLocalPersistence
} from "https://www.gstatic.com/firebasejs/10.8.0/firebase-auth.js";

import {
  getFirestore,
  doc,
  setDoc
} from "https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js";

// -------------------- Firebase Config --------------------
const firebaseConfig = {
  apiKey: "AIzaSyCMXrhsk1cEWqu3fFG2XoI3bDTiEd3Huyw",
  authDomain: "instagram-replica-5b4df.firebaseapp.com",
  projectId: "instagram-replica-5b4df",
  storageBucket: "instagram-replica-5b4df.firebasestorage.app",
  messagingSenderId: "415541720560",
  appId: "1:415541720560:web:190bf12b74ff7510ac5935"
};

// -------------------- Firebase Init --------------------
let app;
let auth;
let db;

try {
  app = initializeApp(firebaseConfig);
  auth = getAuth(app);
  db = getFirestore(app);
  
  // Set persistence to LOCAL to keep user logged in
  setPersistence(auth, browserLocalPersistence)
    .catch(error => {
      console.error("Persistence error:", error);
    });
    
} catch (error) {
  console.error("Firebase initialization error:", error);
}

// -------------------- Helper Functions --------------------
const setTokenCookie = async (user) => {
  if (!user) {
    console.error("No user provided to setTokenCookie");
    return;
  }
  
  try {
    const idToken = await getIdToken(user, true);
    
    // Set cookie
    document.cookie = `token=${idToken}; path=/; SameSite=Strict`;
    
    // Set localStorage
    localStorage.setItem('authToken', idToken);
    
    return idToken;
  } catch (error) {
    console.error("Error setting token cookie:", error);
    throw error;
  }
};

// Initialize user session with backend
const initUserSession = async (token) => {
  try {
    const response = await fetch("/auth/init", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json"
      }
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(`Server error: ${errorData.detail || response.statusText}`);
    }
    
    return await response.json();
  } catch (error) {
    console.error("Failed to initialize session:", error);
    throw error;
  }
};

// Add auth token to all fetch requests
const originalFetch = window.fetch;
window.fetch = function(url, options = {}) {
  const token = localStorage.getItem('authToken');
  
  if (token) {
    options.headers = {
      ...options.headers,
      'Authorization': `Bearer ${token}`
    };
  }
  
  return originalFetch(url, options);
};

// -------------------- DOM Elements --------------------
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const loginBtn = document.getElementById("login");
const signUpBtn = document.getElementById("sign-up");
const signOutBtn = document.getElementById("sign-out");
const loadingSpinner = document.getElementById("loading-spinner");
const errorMessageElement = document.getElementById("error-message");

// Show/hide loading spinner
const showLoading = () => {
  if (loadingSpinner) loadingSpinner.style.display = "block";
};

const hideLoading = () => {
  if (loadingSpinner) loadingSpinner.style.display = "none";
};

// Display error messages to user
const showError = (message) => {
  if (errorMessageElement) {
    errorMessageElement.textContent = message;
    errorMessageElement.style.display = "block";
  } else {
    alert(message);
  }
};

// -------------------- Sign Up --------------------
if (signUpBtn) {
  signUpBtn.addEventListener("click", async () => {
    const email = emailInput.value.trim();
    const password = passwordInput.value.trim();
    const roleInput = document.querySelector('input[name="role"]:checked');
    const role = roleInput ? roleInput.value : "user";

    if (!email || !password) {
      showError("Please enter both email and password");
      return;
    }

    try {
      showLoading();
      
      const userCredential = await createUserWithEmailAndPassword(auth, email, password);
      const user = userCredential.user;

      // Create User document in Firestore
      await setDoc(doc(db, "users", user.uid), {
        id: user.uid,
        email: user.email,
        role: role,
        following: [],
        followers: [],
        created_at: new Date().toISOString()
      });

      const token = await setTokenCookie(user);
      await initUserSession(token);
      
      window.location.href = "/"; // Redirect to home after signup
    } catch (error) {
      console.error("Signup error:", error);
      showError(`Signup failed: ${error.message}`);
    } finally {
      hideLoading();
    }
  });
}

// -------------------- Login --------------------
if (loginBtn) {
  loginBtn.addEventListener("click", async () => {
    const email = emailInput.value.trim();
    const password = passwordInput.value.trim();

    if (!email || !password) {
      showError("Please enter both email and password");
      return;
    }

    try {
      showLoading();
      
      const userCredential = await signInWithEmailAndPassword(auth, email, password);
      const token = await setTokenCookie(userCredential.user);
      
      try {
        await initUserSession(token);
        window.location.href = "/"; // Redirect to home after login
      } catch (sessionError) {
        showError(`Session initialization failed: ${sessionError.message}`);
      }
    } catch (error) {
      console.error("Login error:", error);
      showError(`Login failed: ${error.message}`);
    } finally {
      hideLoading();
    }
  });
}

// -------------------- Logout --------------------
if (signOutBtn) {
  signOutBtn.addEventListener("click", async () => {
    try {
      showLoading();
      await signOut(auth);
      
      // Clear tokens
      document.cookie = "token=; Max-Age=0; path=/; SameSite=Strict";
      localStorage.removeItem('authToken');
      
      window.location.href = "/login";
    } catch (error) {
      console.error("Sign out error:", error);
      showError(`Sign out failed: ${error.message}`);
    } finally {
      hideLoading();
    }
  });
}

// -------------------- Auth State Listener --------------------
onAuthStateChanged(auth, async (user) => {
  if (user) {
    try {
      const token = await setTokenCookie(user);
      
      // Don't redirect during auth state change if we're on login/signup
      const isAuthPage = window.location.pathname.includes('login') || 
                         window.location.pathname.includes('signup');
      
      if (!isAuthPage) {
        try {
          await initUserSession(token);
        } catch (error) {
          console.error("Session initialization failed:", error);
          if (error.message.includes("401") || error.message.includes("unauthorized")) {
            window.location.href = "/login"; // Token invalid, redirect to login
          }
        }
      }
    } catch (err) {
      console.error("User token refresh failed:", err);
    }
  } else {
    console.log("No user logged in");
    // Only redirect if we're not already on login/signup pages
    const isAuthPage = window.location.pathname.includes('login') || 
                       window.location.pathname.includes('signup');
    
    if (!isAuthPage) {
      window.location.href = "/login";
    }
  }
});

// Check if we're on a protected page and redirect if no auth
document.addEventListener('DOMContentLoaded', () => {
  const token = localStorage.getItem('authToken');
  const isAuthPage = window.location.pathname.includes('login') || 
                     window.location.pathname.includes('signup');
  
  if (!isAuthPage && !token) {
    window.location.href = "/login";
  }
});