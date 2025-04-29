import os
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Form, HTTPException, status, Cookie, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import google.oauth2.id_token
from google.auth.transport import requests
from google.cloud import firestore
from typing import Optional, List

# Firebase Admin SDK JSON key
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "firebase-key.json"  # Path to your Firebase key

# Initialize FastAPI app
app = FastAPI()

# Firestore setup
firestore_db = firestore.Client()
firebase_request_adapter = requests.Request()

# Static + template setup
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ------------------------
# Helper: Auth + Firestore
# ------------------------
async def get_auth_token(request: Request, token: Optional[str] = Cookie(None)):
    """Extract the authentication token from either cookies or Authorization header"""
    # First try to get from Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split("Bearer ")[1]
    
    # If not in header, try cookie
    if token:
        return token
    
    # If we can't find a token, raise an exception
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated. Please log in.",
        headers={"WWW-Authenticate": "Bearer"},
    )

# Add this function after the get_current_user function and before your route handlers

def get_user_by_id(user_id: str):
    """Get a user by their ID"""
    user_ref = firestore_db.collection("users").document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_data = user_doc.to_dict()
    user_data["id"] = user_id
    return user_data

def get_user_from_token(id_token_str: str):
    try:
        # Verify the Firebase ID token using Google's OAuth2
        claims = google.oauth2.id_token.verify_firebase_token(id_token_str, firebase_request_adapter)

        # Token expiration time and grace period (e.g., 5 minutes)
        expiration_time = datetime.utcfromtimestamp(claims["exp"])
        grace_period = timedelta(minutes=5)
        current_time = datetime.utcnow()

        # If the token is within the grace period of expiration, allow it
        if not (current_time < expiration_time + grace_period):
            raise HTTPException(status_code=401, detail="Token expired")

        user_id = claims["user_id"]
        user_doc_ref = firestore_db.collection("users").document(user_id)

        if not user_doc_ref.get().exists:
            user_doc_ref.set({
                "name": "New User",
                "email": claims.get("email", ""),
                "followers": [],
                "following": [],
                "created_at": datetime.utcnow().isoformat()
            })

        user_data = user_doc_ref.get().to_dict()
        user_data["id"] = user_id
        return user_data

    except Exception as e:
        print(f"Error verifying token or fetching user: {e}")
        raise HTTPException(status_code=401, detail="Token verification failed")

# Dependency to get the current user
async def get_current_user(request: Request, token: Optional[str] = Cookie(None)):
    token_str = await get_auth_token(request, token)
    if not token_str:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    return get_user_from_token(token_str)

# -------------------
# FastAPI Routes
# -------------------

@app.get("/")
async def serve_home(request: Request, user_data = Depends(get_current_user)):
    """Home page route - requires authentication"""
    user_id = user_data["id"]
    
    # Fetch feed posts (this is a placeholder - you might want to fetch posts from users that the current user follows)
    posts_ref = firestore_db.collection("posts").order_by("date", direction=firestore.Query.DESCENDING).limit(10)
    posts = [post.to_dict() for post in posts_ref.stream()]
    
    return templates.TemplateResponse(
        "home.html", 
        {"request": request, "user_id": user_id, "user_data": user_data, "posts": posts}
    )

@app.get("/login")
async def serve_login():
    """Login page - no authentication required"""
    return HTMLResponse(open("templates/login.html").read())

@app.get("/signup")
async def serve_signup():
    """Signup page - no authentication required"""
    return HTMLResponse(open("templates/signup.html").read())

@app.get("/profile/{user_id}")
async def serve_profile(request: Request, user_id: str, current_user = Depends(get_current_user)):
    """Profile page - requires authentication"""
    # Fetch user data (e.g., posts, followers) from Firestore based on user_id
    user_ref = firestore_db.collection("users").document(user_id)
    user_data = user_ref.get().to_dict()
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")

    # Add the user ID to the user data
    user_data["id"] = user_id

    # Retrieve posts for the user
    posts_ref = firestore_db.collection("posts").where("user_id", "==", user_id).order_by("date", direction=firestore.Query.DESCENDING)
    posts = [post.to_dict() for post in posts_ref.stream()]

    # Check if this is the current user's profile
    is_own_profile = current_user["id"] == user_id

    return templates.TemplateResponse(
        "profile.html", 
        {
            "request": request, 
            "user_data": user_data, 
            "posts": posts,
            "is_own_profile": is_own_profile,
            "current_user": current_user
        }
    )


# Add these routes to your main.py file

@app.get("/edit-profile")
async def edit_profile(request: Request, current_user = Depends(get_current_user)):
    """Edit profile page - requires authentication"""
    return templates.TemplateResponse(
        "update_profile.html", 
        {"request": request, "user_data": current_user}
    )

@app.post("/update-profile")
async def update_profile(
    request: Request,
    name: str = Form(...),
    username: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    gender: Optional[str] = Form(None),
    private_account: bool = Form(False),
    current_user = Depends(get_current_user)
):
    """Update user profile - requires authentication"""
    user_id = current_user["id"]
    user_ref = firestore_db.collection("users").document(user_id)
    
    # Process form data and prepare update payload
    update_data = {
        "name": name,
        "username": username,
        "bio": bio,
        "website": website,
        "phone": phone,
        "gender": gender,
        "private_account": private_account,
        "updated_at": datetime.utcnow().isoformat()
    }
    
    # Handle profile picture upload
    form = await request.form()
    profile_picture = form.get("profile_picture")
    
    if profile_picture and profile_picture.filename:
        # Make sure the uploads directory exists
        os.makedirs("static/uploads/profiles", exist_ok=True)
        
        # Save the image to disk
        image_filename = f"{user_id}_{datetime.utcnow().timestamp()}_{profile_picture.filename}"
        image_path = f"static/uploads/profiles/{image_filename}"
        
        with open(image_path, "wb") as f:
            f.write(await profile_picture.read())
        
        # Add profile picture path to update data
        update_data["profile_picture"] = f"/{image_path}"
    
    # Update user profile in Firestore
    user_ref.update(update_data)
    
    # Redirect to profile page
    return RedirectResponse(url=f"/profile/{user_id}", status_code=302)


@app.get("/create-post")
async def serve_create_post(request: Request, user_data = Depends(get_current_user)):
    """Create post page - requires authentication"""
    return templates.TemplateResponse("create_post.html", {"request": request, "user_id": user_data["id"]})

@app.post("/auth/init")
async def init_session(request: Request):
    """Initialize user session after login"""
    try:
        token_str = await get_auth_token(request)
        user_data = get_user_from_token(token_str)
        
        # Set token cookie for browsers
        response = JSONResponse(content={"message": "Session initialized", "user": user_data})
        response.set_cookie(key="token", value=token_str, httponly=True, path="/")
        
        return response
    
    except Exception as e:
        print(f"Session init error: {e}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

@app.post("/create-post")
async def create_post(
    request: Request,
    caption: str = Form(...),
    user_data = Depends(get_current_user)
):
    """Create a new post - requires authentication"""
    user_id = user_data["id"]
    
    # Process the form data
    form = await request.form()
    image = form.get("image")
    
    if not image:
        raise HTTPException(status_code=400, detail="Image file is required")

    # Make sure the uploads directory exists
    os.makedirs("static/uploads", exist_ok=True)
    
    # Save the image to disk
    image_filename = f"{user_id}_{datetime.utcnow().timestamp()}_{image.filename}"
    image_path = f"static/uploads/{image_filename}"
    
    with open(image_path, "wb") as f:
        f.write(await image.read())

    # Create the post in Firestore
    post_data = {
        "user_id": user_id,
        "caption": caption,
        "image_url": f"/{image_path}",  # Use relative path for frontend
        "date": datetime.utcnow().isoformat(),
        "likes": 0,
        "comments": []
    }

    # Add the post to Firestore
    post_ref = firestore_db.collection("posts").document()
    post_ref.set(post_data)
    
    # Get the post ID and add it to the post data
    post_id = post_ref.id
    post_ref.update({"id": post_id})

    return RedirectResponse(url=f"/profile/{user_id}", status_code=302)


@app.post("/follow/{user_id}")
async def follow_user(
    user_id: str,
    current_user = Depends(get_current_user)
):
    """Follow a user - requires authentication"""
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")
    
    # Get user to follow
    user_to_follow = get_user_by_id(user_id)
    
    # Update current user's following list
    current_user_ref = firestore_db.collection("users").document(current_user["id"])
    if user_id not in current_user.get("following", []):
        current_user_ref.update({
            "following": firestore.ArrayUnion([user_id])
        })
    
    # Update followed user's followers list
    user_to_follow_ref = firestore_db.collection("users").document(user_id)
    if current_user["id"] not in user_to_follow.get("followers", []):
        user_to_follow_ref.update({
            "followers": firestore.ArrayUnion([current_user["id"]])
        })
    
    # Redirect back to the profile page
    referer = f"/profile/{user_id}"
    return RedirectResponse(url=referer, status_code=302)

@app.post("/unfollow/{user_id}")
async def unfollow_user(
    user_id: str,
    current_user = Depends(get_current_user)
):
    """Unfollow a user - requires authentication"""
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Cannot unfollow yourself")
    
    # Get user to unfollow
    user_to_unfollow = get_user_by_id(user_id)
    
    # Update current user's following list
    current_user_ref = firestore_db.collection("users").document(current_user["id"])
    if user_id in current_user.get("following", []):
        current_user_ref.update({
            "following": firestore.ArrayRemove([user_id])
        })
    
    # Update unfollowed user's followers list
    user_to_unfollow_ref = firestore_db.collection("users").document(user_id)
    if current_user["id"] in user_to_unfollow.get("followers", []):
        user_to_unfollow_ref.update({
            "followers": firestore.ArrayRemove([current_user["id"]])
        })
    
    # Redirect back to the profile page
    referer = f"/profile/{user_id}"
    return RedirectResponse(url=referer, status_code=302)

@app.get("/followers/{user_id}")
async def show_followers(
    request: Request,
    user_id: str,
    current_user = Depends(get_current_user)
):
    """Show followers of a user - requires authentication"""
    profile_user = get_user_by_id(user_id)
    follower_ids = profile_user.get("followers", [])
    
    # Fetch complete user objects for all followers
    followers = []
    for follower_id in follower_ids:
        try:
            follower = get_user_by_id(follower_id)
            followers.append(follower)
        except HTTPException:
            # Skip if user not found
            continue
    
    # Sort followers by most recent first (based on when they followed)
    # Since we don't track the follow date, we'll just use alphabetical for now
    followers = sorted(followers, key=lambda x: x.get("name", "").lower())
    
    return templates.TemplateResponse(
        "followers.html",
        {
            "request": request,
            "profile_user": profile_user,
            "followers": followers,
            "current_user": current_user
        }
    )

@app.get("/following/{user_id}")
async def show_following(
    request: Request,
    user_id: str,
    current_user = Depends(get_current_user)
):
    """Show users that a user is following - requires authentication"""
    profile_user = get_user_by_id(user_id)
    following_ids = profile_user.get("following", [])
    
    # Fetch complete user objects for all following
    following_users = []
    for following_id in following_ids:
        try:
            following_user = get_user_by_id(following_id)
            following_users.append(following_user)
        except HTTPException:
            # Skip if user not found
            continue
    
    # Sort by name for now (since we don't track follow date)
    following_users = sorted(following_users, key=lambda x: x.get("name", "").lower())
    
    return templates.TemplateResponse(
        "following.html",
        {
            "request": request,
            "profile_user": profile_user,
            "following_users": following_users,
            "current_user": current_user
        }
    )

@app.get("/search")
async def search_users(
    request: Request,
    query: Optional[str] = Query(None),
    current_user = Depends(get_current_user)
):
    """Search for users by profile name"""
    search_results = []
    
    if query:
        # Query Firestore for users whose name starts with the query
        users_ref = firestore_db.collection("users")
        results = users_ref.stream()
        
        # Filter results where name starts with query (case insensitive)
        query_lower = query.lower()
        for user in results:
            user_data = user.to_dict()
            user_data["id"] = user.id
            
            if user_data.get("name", "").lower().startswith(query_lower):
                search_results.append(user_data)
        
        # Sort results alphabetically
        search_results = sorted(search_results, key=lambda x: x.get("name", "").lower())
    
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "user_id": current_user["id"],
            "current_user": current_user,
            "query": query,
            "search_results": search_results
        }
    )

@app.post("/add-comment/{post_id}")
async def add_comment(
    request: Request,
    post_id: str,
    comment_text: str = Form(...),
    current_user = Depends(get_current_user)
):
    """Add a comment to a post"""
    # Validate comment length
    if len(comment_text) > 200:
        raise HTTPException(status_code=400, detail="Comment too long, maximum 200 characters")
    
    # Get the post
    post_ref = firestore_db.collection("posts").document(post_id)
    post = post_ref.get()
    
    if not post.exists:
        raise HTTPException(status_code=404, detail="Post not found")
    
    # Create comment object
    comment = {
        "user_id": current_user["id"],
        "username": current_user["name"],
        "text": comment_text,
        "date": datetime.utcnow().isoformat()
    }
    
    # Add comment to the post
    post_ref.update({
        "comments": firestore.ArrayUnion([comment])
    })
    
    # Redirect back to the page where the comment was made
    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=302)


# Add this at the end of your file to run the app with Uvicorn when the script is executed directly
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)