# Deployment Instructions (Mongo + Render)

This application is now a **Headless FastAPI Backend** using MongoDB. It separates the frontend and backend concerns.

## 1. Prerequisites
- A **MongoDB Atlas** account (or any MongoDB provider).
- A **Render** account.
- A **Frontend** (e.g., React/Vue/Svelte on Vercel/Netlify/Render) configured to consume this API.

## 2. Local Development
1. **Unzip/Clone** the project.
2. In the root directory, create a `.env` file:
   ```env
   MONGO_URI=mongodb+srv://<user>:<password>@cluster.mongodb.net/?retryWrites=true&w=majority
   SECRET_KEY=your_development_secret
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the server:
   ```bash
   uvicorn app:app --reload
   ```
   Access the API at `http://localhost:8000`.

## 3. Deploy Backend to Render
1. **Create a Web Service** on Render connected to your repository.
2. **Settings**:
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
3. **Environment Variables** (Add these in Render Dashboard):
   - `MONGO_URI`: Your MongoDB connection string (from Atlas).
   - `SECRET_KEY`: A strong random string for JWT signing.
   - `PYTHON_VERSION`: `3.10.0` (Optional, but recommended)

## 4. Frontend Integration
Since this is now an API, your frontend needs to:
- POST to `/auth/login` to get a JWT.
- Store the JWT.
- Connect to WebSocket at `/ws/{user_id}`.
- POST to `/chat/start` to begin conversations.

The backend is configured to allow CORS requests from:
- `localhost`
- `*.vercel.app`
- `*.onrender.com`

If you deploy your frontend elsewhere, update the `allow_origin_regex` in `app.py`.
