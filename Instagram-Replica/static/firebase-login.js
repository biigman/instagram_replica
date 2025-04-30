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
    return null;
  }
  
  try {
    const idToken = await getIdToken(user, true);
    
    // Set cookie with proper attributes
    document.cookie = `token=${idToken}; path=/; SameSite=Lax; Max-Age=3600`;
    
    // Set localStorage
    localStorage.setItem('authToken', idToken);
    
    return idToken;
  } catch (error) {
    console.error("Error setting token cookie:", error);
    throw error;
  }
};

// Clear all auth tokens
const clearAuthTokens = () => {
  // Clear cookie by setting max-age to 0
  document.cookie = "token=; Max-Age=0; path=/; SameSite=Lax";
  
  // Clear localStorage
  localStorage.removeItem('authToken');
  sessionStorage.removeItem('authToken');
};

// Initialize user session with backend
const initUserSession = async (token) => {
  if (!token) {
    console.error("No token provided to initUserSession");
    return null;
  }

  try {
    const response = await fetch("/auth/init", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
      },
      body: JSON.stringify({ idToken: token })
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(`Server error: ${errorData.error || response.statusText}`);
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
  // Only add auth header to non-auth endpoints
  if (!url.includes('/auth/init') && !url.includes('identitytoolkit.googleapis.com')) {
    const token = localStorage.getItem('authToken');
    
    if (token) {
      options.headers = {
        ...(options.headers || {}),
        'Authorization': `Bearer ${token}`
      };
    }
  }
  
  return originalFetch(url, options);
};

// Show/hide loading spinner
const showLoading = () => {
  const loadingSpinner = document.getElementById("loading-spinner");
  if (loadingSpinner) loadingSpinner.style.display = "block";
};

const hideLoading = () => {
  const loadingSpinner = document.getElementById("loading-spinner");
  if (loadingSpinner) loadingSpinner.style.display = "none";
};

// Display error messages to user
const showError = (message) => {
  const errorMessageElement = document.getElementById("error-message");
  if (errorMessageElement) {
    errorMessageElement.textContent = message;
    errorMessageElement.style.display = "block";
  } else {
    alert(message);
  }
};

// Clear error messages
const clearError = () => {
  const errorMessageElement = document.getElementById("error-message");
  if (errorMessageElement) {
    errorMessageElement.textContent = "";
    errorMessageElement.style.display = "none";
  }
};

// -------------------- INITIALIZE PAGE SPECIFIC FUNCTIONS --------------------
document.addEventListener('DOMContentLoaded', () => {
  // Format dates if we're on a page with posts
  formatAllDates();
  
  // Check which page we're on and initialize accordingly
  initPage();
  
  // Add auth state listener
  initAuthStateListener();
});

// Format date function that can be used on any page
function formatDate(dateString) {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now - date;
  const diffSeconds = Math.floor(diffMs / 1000);
  const diffMinutes = Math.floor(diffSeconds / 60);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);
  
  if (isNaN(date.getTime())) {
    return dateString; // Return original if invalid
  }
  
  if (diffSeconds < 60) {
    return `${diffSeconds} seconds ago`;
  } else if (diffMinutes < 60) {
    return `${diffMinutes} minute${diffMinutes !== 1 ? 's' : ''} ago`;
  } else if (diffHours < 24) {
    return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
  } else if (diffDays < 7) {
    return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
  } else {
    return date.toLocaleDateString();
  }
}

// Format all date elements on the page
function formatAllDates() {
  const dates = document.querySelectorAll('.post-date');
  if (dates.length > 0) {
    dates.forEach(dateElement => {
      const originalDate = dateElement.textContent.trim();
      dateElement.textContent = formatDate(originalDate);
    });
  }
}

// Show all comments functionality for home and profile pages
window.showAllComments = function(postId) {
  const post = document.getElementById(postId);
  if (post) {
    const commentsContainer = post.querySelector('.comments-container');
    const allComments = post.querySelector('.all-comments');
    const showMoreButton = post.querySelector('.show-more');
    
    if (commentsContainer && allComments && showMoreButton) {
      commentsContainer.style.display = 'none';
      allComments.style.display = 'block';
      showMoreButton.style.display = 'none';
    }
  }
};

// Initialize page based on URL
function initPage() {
  const path = window.location.pathname;
  
  // Initialize login page
  if (path.includes('/login')) {
    initLoginPage();
  }
  
  // Initialize signup page
  else if (path.includes('/signup')) {
    initSignupPage();
  }
  
  // Initialize pages with sign-out button
  const signOutBtn = document.getElementById("sign-out");
  if (signOutBtn) {
    initSignOutButton(signOutBtn);
  }
}

// -------------------- Login Page --------------------
function initLoginPage() {
  const loginBtn = document.getElementById("login");
  const emailInput = document.getElementById("email");
  const passwordInput = document.getElementById("password");
  
  if (loginBtn && emailInput && passwordInput) {
    loginBtn.addEventListener("click", async () => {
      clearError();
      const email = emailInput.value.trim();
      const password = passwordInput.value.trim();

      if (!email || !password) {
        showError("Please enter both email and password");
        return;
      }

      try {
        showLoading();
        
        // Clear any existing tokens before login
        clearAuthTokens();
        
        const userCredential = await signInWithEmailAndPassword(auth, email, password);
        const token = await setTokenCookie(userCredential.user);
        
        if (token) {
          try {
            await initUserSession(token);
            window.location.href = "/"; // Redirect to home after login
          } catch (sessionError) {
            console.error("Session init error:", sessionError);
            showError(`Session initialization failed: ${sessionError.message}`);
          }
        } else {
          showError("Failed to get authentication token");
        }
      } catch (error) {
        console.error("Login error:", error);
        showError(`Login failed: ${error.message}`);
      } finally {
        hideLoading();
      }
    });
    
    // Add enter key support
    [emailInput, passwordInput].forEach(input => {
      input.addEventListener("keypress", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          loginBtn.click();
        }
      });
    });
  }
}

// -------------------- Signup Page --------------------
function initSignupPage() {
  console.log("Initializing signup page");
  const nameInput = document.getElementById("name");
  const emailInput = document.getElementById("email");
  const passwordInput = document.getElementById("password");
  const signUpBtn = document.getElementById("sign-up");
  
  if (signUpBtn && emailInput && passwordInput) {
    console.log("Found signup form elements");
    
    signUpBtn.addEventListener("click", async () => {
      clearError();
      const email = emailInput.value.trim();
      const password = passwordInput.value.trim();
      const name = nameInput ? nameInput.value.trim() : email.split('@')[0];

      if (!email || !password || (nameInput && !name)) {
        showError("Please complete all required fields");
        return;
      }

      // Disable the button to prevent multiple clicks
      signUpBtn.disabled = true;
      signUpBtn.classList.add('disabled');
      
      try {
        showLoading();
        console.log("Creating new account for:", email);
        
        // Create new user
        const userCredential = await createUserWithEmailAndPassword(auth, email, password);
        const user = userCredential.user;
        console.log("User created successfully");

        // Create User document in Firestore with name
        try {
          await setDoc(doc(db, "users", user.uid), {
            id: user.uid,
            email: user.email,
            name: name,
            role: "user",
            following: [],
            followers: [],
            created_at: new Date().toISOString()
          });
          
          console.log("User document created successfully");
        } catch (firestoreError) {
          console.error("Error creating user document:", firestoreError);
          // Continue with token setup even if Firestore fails
        }

        // Get token and set cookies
        const token = await setTokenCookie(user);
        
        if (!token) {
          throw new Error("Failed to get authentication token");
        }
        
        // Initialize session with backend
        await initUserSession(token);
        
        // Show success message and redirect
        const successMessage = "Sign up successful! Redirecting...";
        showError(successMessage);
        const errorMessageElement = document.getElementById("error-message");
        if (errorMessageElement) {
          errorMessageElement.style.color = "#2ecc71"; // Green color for success
          errorMessageElement.style.backgroundColor = "#e8f5e9"; // Light green background
        }
        
        // Redirect to home after a short delay
        setTimeout(() => {
          window.location.href = "/";
        }, 1500);
        // Comment: Redirect to home after a short delay
      } catch (error) {
        console.error("Signup error:", error);
        showError(`Signup failed: ${error.message}`);
        
        // Re-enable the button if there was an error
        signUpBtn.disabled = false;
        signUpBtn.classList.remove('disabled');
      } finally {
        hideLoading();
      }
    });

    // Add form validation if on signup page
    if (nameInput && emailInput && passwordInput) {
      const validateForm = () => {
        const name = nameInput.value.trim();
        const email = emailInput.value.trim();
        const password = passwordInput.value.trim();
        
        if (!name || !email || !password) {
          return false;
        }
        
        // Simple email validation
        const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailPattern.test(email)) {
          return false;
        }
        
        // Password validation (at least 6 characters)
        if (password.length < 6) {
          return false;
        }
        
        return true;
      };

      // Enable/disable button based on form validity
      const checkFormValidity = () => {
        if (validateForm()) {
          signUpBtn.disabled = false;
          signUpBtn.classList.remove('disabled');
        } else {
          signUpBtn.disabled = true;
          signUpBtn.classList.add('disabled');
        }
      };

      // Add input event listeners
      nameInput.addEventListener('input', checkFormValidity);
      emailInput.addEventListener('input', checkFormValidity);
      passwordInput.addEventListener('input', checkFormValidity);
      
      // Initial check
      checkFormValidity();
      
      // Add enter key support
      [nameInput, emailInput, passwordInput].forEach(input => {
        input.addEventListener("keypress", (event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            if (!signUpBtn.disabled) {
              signUpBtn.click();
            }
          }
        });
      });
    }
  } else {
    console.error("Could not find all signup form elements");
  }
}

// -------------------- Sign Out --------------------
function initSignOutButton(signOutBtn) {
  signOutBtn.addEventListener("click", async () => {
    try {
      showLoading();
      
      // First clear all tokens
      clearAuthTokens();
      
      // Then sign out from Firebase
      await signOut(auth);
      
      // Redirect to login page after a short delay
      setTimeout(() => {
        window.location.href = "/login";
      }, 500);
    } catch (error) {
      console.error("Sign out error:", error);
      showError(`Sign out failed: ${error.message}`);
    } finally {
      hideLoading();
    }
  });
}

// -------------------- Auth State Listener --------------------
function initAuthStateListener() {
  onAuthStateChanged(auth, async (user) => {
    console.log("Auth state changed:", user ? "user logged in" : "no user");
    
    const isAuthPage = window.location.pathname.includes('login') || 
                      window.location.pathname.includes('signup');
    
    if (user) {
      try {
        // Check if we already have a valid token
        let token = localStorage.getItem('authToken');
        
        // If no token or token is expired, get a fresh one
        if (!token) {
          token = await setTokenCookie(user);
        }
        
        if (token && !isAuthPage) {
          try {
            await initUserSession(token);
          } catch (error) {
            console.error("Session initialization failed:", error);
            if (error.message.includes("401") || error.message.includes("unauthorized")) {
              clearAuthTokens();
              window.location.href = "/login"; // Token invalid, redirect to login
            }
          }
        } else if (isAuthPage) {
          // If already logged in and on auth page, redirect to home
          console.log("Already logged in, redirecting to home");
          window.location.href = "/";
        }
      } catch (err) {
        console.error("User token refresh failed:", err);
      }
    } else if (!isAuthPage) {
      console.log("No user logged in, redirecting to login");
      window.location.href = "/login";
    }
  });
}

// Check if we're on a protected page and redirect if no auth
const token = localStorage.getItem('authToken');
const isAuthPage = window.location.pathname.includes('login') || 
                  window.location.pathname.includes('signup');

if (!isAuthPage && !token) {
  console.log("No token found on protected page, redirecting to login");
  window.location.href = "/login";
}