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
from datetime import datetime

# Firebase Admin SDK JSON key
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "firebase-key.json"  

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
    
    # If we can't find a token, return None instead of raising an exception
    return None

def get_user_by_id(user_id: str):
    """Get a user by their ID"""
    try:
        user_ref = firestore_db.collection("users").document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found")
        
        user_data = user_doc.to_dict()
        user_data["id"] = user_id
        
        # Initialize arrays if they don't exist
        if "followers" not in user_data:
            user_data["followers"] = []
        if "following" not in user_data:
            user_data["following"] = []
            
        return user_data
    except Exception as e:
        print(f"Error in get_user_by_id: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving user: {str(e)}")

def get_user_from_token(id_token_str: str):
    """Verify Firebase ID token and retrieve user information"""
    if not id_token_str:
        print("No token provided to get_user_from_token")
        return None
        
    try:
        # Verify the Firebase ID token using Google's OAuth2
        claims = google.oauth2.id_token.verify_firebase_token(id_token_str, firebase_request_adapter)
        
        if not claims:
            print("Failed to verify token: Claims is empty")
            return None

        # Token expiration time and grace period (e.g., 5 minutes)
        expiration_time = datetime.utcfromtimestamp(claims.get("exp", 0))
        grace_period = timedelta(minutes=5)
        current_time = datetime.utcnow()

        # If the token is within the grace period of expiration, allow it
        if not (current_time < expiration_time + grace_period):
            print("Token expired")
            return None

        # Different Firebase implementations might use different claim keys
        user_id = claims.get("user_id") or claims.get("sub") or claims.get("uid")
        if not user_id:
            print("No user ID found in token claims")
            print(f"Available claims: {claims}")
            return None
            
        # Try to get user from Firestore, create if it doesn't exist
        user_doc_ref = firestore_db.collection("users").document(user_id)
        user_doc = user_doc_ref.get()

        if user_doc.exists:
            user_data = user_doc.to_dict()
            user_data["id"] = user_id
            
            # Make sure arrays exist
            if "followers" not in user_data:
                user_doc_ref.update({"followers": []})
                user_data["followers"] = []
            if "following" not in user_data:
                user_doc_ref.update({"following": []})
                user_data["following"] = []
                
            return user_data
        else:
            # Create new user document with initialized arrays
            new_user = {
                "name": claims.get("name", claims.get("email", "").split('@')[0]),
                "email": claims.get("email", ""),
                "created_at": datetime.utcnow().isoformat(),
                "followers": [],
                "following": []
            }
            user_doc_ref.set(new_user)
            
            # Return user data with ID
            new_user["id"] = user_id
            return new_user

    except ValueError as e:
        # This happens if the token is invalid
        print(f"Token validation error: {e}")
        return None
    except Exception as e:
        print(f"Error verifying token or fetching user: {e}")
        return None

# Dependency to get the current user (optional)
async def get_current_user(request: Request, token: Optional[str] = Cookie(None)):
    token_str = await get_auth_token(request, token)
    if not token_str:
        return None
    
    return get_user_from_token(token_str)

# Dependency to get the current user (required)
async def get_required_user(request: Request, token: Optional[str] = Cookie(None)):
    token_str = await get_auth_token(request, token)
    if not token_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_data = get_user_from_token(token_str)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user_data

# -------------------
# FastAPI Routes
# -------------------

@app.get("/")
async def serve_home(request: Request, user_data = Depends(get_current_user)):
    """Home page route - if not authenticated, redirect to login"""
    # If user is not authenticated, redirect to login page
    if not user_data:
        return RedirectResponse(url="/login", status_code=302)
    
    user_id = user_data["id"]
    
    # Fetch feed posts (this is a placeholder - you might want to fetch posts from users that the current user follows)
    posts_ref = firestore_db.collection("posts").order_by("date", direction=firestore.Query.DESCENDING).limit(10)
    posts = []
    
    for post_doc in posts_ref.stream():
        post = post_doc.to_dict()
        
        # Fetch user information for each post
        try:
            post_user_ref = firestore_db.collection("users").document(post["user_id"])
            post_user_data = post_user_ref.get().to_dict()
            
            if post_user_data:
                post["user_name"] = post_user_data.get("name", "")
                post["user_profile_picture"] = post_user_data.get("profile_picture", "")
        except Exception as e:
            print(f"Error fetching user data for post: {e}")
        
        # Format the date
        try:
            from datetime import datetime
            date_obj = datetime.fromisoformat(post["date"])
            from dateutil.relativedelta import relativedelta
            now = datetime.utcnow()
            diff = relativedelta(now, date_obj)
            
            if diff.days > 7:
                # Format as MM/DD/YYYY
                post["formatted_date"] = date_obj.strftime("%m/%d/%Y")
            elif diff.days > 0:
                post["formatted_date"] = f"{diff.days} day{'s' if diff.days != 1 else ''} ago"
            elif diff.hours > 0:
                post["formatted_date"] = f"{diff.hours} hour{'s' if diff.hours != 1 else ''} ago"
            elif diff.minutes > 0:
                post["formatted_date"] = f"{diff.minutes} minute{'s' if diff.minutes != 1 else ''} ago"
            else:
                post["formatted_date"] = "Just now"
        except Exception as e:
            print(f"Error formatting date: {e}")
            # Keep the original date format as fallback
        
        posts.append(post)
    
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
    # If user is not authenticated, redirect to login page
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
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

@app.get("/edit-profile")
async def edit_profile(request: Request, current_user = Depends(get_current_user)):
    """Edit profile page - requires authentication"""
    # If user is not authenticated, redirect to login page
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
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
    current_user = Depends(get_required_user)
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
async def show_create_post_page(request: Request, user_data = Depends(get_required_user)):
    """Render the create post page - requires authentication"""
    return templates.TemplateResponse(
        "create_post.html", 
        {"request": request, "user_id": user_data["id"]}
    )

@app.post("/create-post")
async def create_post(
    request: Request,
    caption: str = Form(...),
    user_data = Depends(get_required_user)
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
        "user_name": user_data.get("name", ""),  # Add username to post data
        "caption": caption,
        "image_url": f"/{image_path}",  # Use relative path for frontend
        "date": datetime.utcnow().isoformat(),
        "likes": 0,
        "comments": []
    }


    
    
    # Add profile picture if available
    if "profile_picture" in user_data:
        post_data["user_profile_picture"] = user_data["profile_picture"]

    # Add the post to Firestore
    post_ref = firestore_db.collection("posts").document()
    post_ref.set(post_data)
    
    # Get the post ID and add it to the post data
    post_id = post_ref.id
    post_ref.update({"id": post_id})

    return RedirectResponse(url=f"/profile/{user_id}", status_code=302)



@app.post("/auth/init")
async def init_session(request: Request):
    """Initialize user session after login"""
    try:
        # 1. Try Authorization header
        auth_header = request.headers.get("Authorization")
        token_str = None

        if auth_header and auth_header.startswith("Bearer "):
            token_str = auth_header.split("Bearer ")[1]
        else:
            # 2. Fallback to JSON body
            try:
                body = await request.json()
                token_str = body.get("idToken")
            except Exception:
                pass

        if not token_str:
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": "No token provided"}
            )

        # 3. Verify token using your helper
        user_data = get_user_from_token(token_str)
        if not user_data:
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": "Invalid or expired token"}
            )

        # 4. Set HTTP-only cookie (optional)
        response = JSONResponse(
            content={"success": True, "message": "Session initialized", "user": user_data}
        )
        response.set_cookie(
        key="token",
        value=token_str,
        httponly=True,
        path="/",
        max_age=3600,
        secure=True,          
        samesite="None"
    )


        return response

    except Exception as e:
        print(f"Session init error: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Server error: " + str(e)}
        )
    
@app.post("/create-post")
async def create_post(
    request: Request,
    caption: str = Form(...),
    user_data = Depends(get_required_user)
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
    request: Request,
    redirect_url: Optional[str] = Form(None),
    current_user = Depends(get_required_user)
):
    """Follow a user - requires authentication"""
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")
    
    # Check if user to follow exists
    user_to_follow_ref = firestore_db.collection("users").document(user_id)
    user_to_follow_doc = user_to_follow_ref.get()
    
    if not user_to_follow_doc.exists:
        raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found")
    
    user_to_follow = user_to_follow_doc.to_dict()
    
    # Update current user's following list
    current_user_ref = firestore_db.collection("users").document(current_user["id"])
    
    # Initialize arrays if they don't exist
    if "following" not in current_user:
        current_user_ref.update({"following": []})
        current_user["following"] = []
    
    if user_id not in current_user["following"]:
        current_user_ref.update({
            "following": firestore.ArrayUnion([user_id])
        })
    
    # Initialize followers array if it doesn't exist
    if "followers" not in user_to_follow:
        user_to_follow_ref.update({"followers": []})
        user_to_follow["followers"] = []
    
    # Update followed user's followers list
    if current_user["id"] not in user_to_follow.get("followers", []):
        user_to_follow_ref.update({
            "followers": firestore.ArrayUnion([current_user["id"]])
        })
    
    # Check if a custom redirect URL was provided (for staying on search page)
    if redirect_url:
        return RedirectResponse(url=redirect_url, status_code=302)
    
    # Otherwise, redirect back to the profile page
    return RedirectResponse(url=f"/profile/{user_id}", status_code=302)

@app.post("/unfollow/{user_id}")
async def unfollow_user(
    user_id: str,
    request: Request,
    redirect_url: Optional[str] = Form(None),
    current_user = Depends(get_required_user)
):
    """Unfollow a user - requires authentication"""
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Cannot unfollow yourself")
    
    # Check if user to unfollow exists
    user_to_unfollow_ref = firestore_db.collection("users").document(user_id)
    user_to_unfollow_doc = user_to_unfollow_ref.get()
    
    if not user_to_unfollow_doc.exists:
        raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found")
    
    user_to_unfollow = user_to_unfollow_doc.to_dict()
    
    # Update current user's following list
    current_user_ref = firestore_db.collection("users").document(current_user["id"])
    
    # Only try to remove if the "following" array exists and contains the target user
    if "following" in current_user and user_id in current_user["following"]:
        current_user_ref.update({
            "following": firestore.ArrayRemove([user_id])
        })
    
    # Only try to remove if the "followers" array exists and contains the current user
    if "followers" in user_to_unfollow and current_user["id"] in user_to_unfollow["followers"]:
        user_to_unfollow_ref.update({
            "followers": firestore.ArrayRemove([current_user["id"]])
        })
    
    # Check if a custom redirect URL was provided (for staying on search page)
    if redirect_url:
        return RedirectResponse(url=redirect_url, status_code=302)
    
    # Otherwise, redirect back to the profile page
    return RedirectResponse(url=f"/profile/{user_id}", status_code=302)

@app.get("/followers/{user_id}")
async def show_followers(
    request: Request,
    user_id: str,
    current_user = Depends(get_current_user)
):
    """Show followers of a user - requires authentication"""
    # If user is not authenticated, redirect to login page
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
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
    # If user is not authenticated, redirect to login page
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
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
    # If user is not authenticated, redirect to login page
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
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
    current_user = Depends(get_required_user)
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