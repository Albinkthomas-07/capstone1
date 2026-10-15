import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

app = FastAPI(title="Embeddable Widget & Lead-Capture Platform", version="1.0.0")

# 1. CORS Configuration for public widget submission and config APIs[cite: 3, 5, 10, 11]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Public internet embed: allow all origins to load/submit
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# In-memory database mocks (replace with PostgreSQL / SQLAlchemy for production)
WIDGET_DB = {
    "abc123": {
        "id": "abc123",
        "tenant_id": "tenant_alpha",
        "title": "Contact Us",
        "fields": ["name", "email", "message"],
    }
}
SUBMISSIONS_DB = []


# 2. Pydantic Models for Boundary Validation[cite: 5, 10]
class SubmissionPayload(BaseModel):
  widget_id: str = Field(..., min_length=1)
  name: str = Field(..., min_length=1, max_length=100)
  email: EmailStr
  message: str = Field(..., min_length=1, max_length=1000)
  honeypot: str = Field(
      default="", description="Hidden field; if filled, it's a bot"
  )  # Spam control[cite: 5, 11]


# 3. Geo Enrichment Fallback Chain[cite: 4, 11]
async def enrich_with_geo(ip: str) -> dict | None:
  """Try provider A (ip-api.com), fallback to provider B (ipapi.co).

  Degrades gracefully if all fail[cite: 4, 5, 11].
  """
  # Skip lookup for local test IPs
  if ip in ("127.0.0.1", "localhost", "::1"):
    return {"country": "Localhost", "city": "Local Dev"}

  async with httpx.AsyncClient(timeout=3.0) as client:
    # Provider A: ip-api.com (~45 req/min free, no key)[cite: 7, 10]
    try:
      response = await client.get(f"http://ip-api.com/json/{ip}")
      if response.status_code == 200:
        data = response.json()
        if data.get("status") == "success":
          return {"country": data.get("country"), "city": data.get("city")}
    except Exception:
      pass  # Provider A failed, proceed to fallback

    # Provider B: ipapi.co (~1,000 requests/day free tier)[cite: 7, 10]
    try:
      response = await client.get(f"https://ipapi.co/{ip}/json/")
      if response.status_code == 200:
        data = response.json()
        if "error" not in data:
          return {"country": data.get("country_name"), "city": data.get("city")}
    except Exception:
      pass  # Provider B also failed

    # All providers down: return None to allow submission to succeed without geo data[cite: 4, 5, 11]
    return None


# 4. Safe Side Effect Handler (e.g., Email notification)[cite: 4, 5, 11]
async def trigger_safe_side_effect(submission_data: dict):
  """Simulates email or webhook trigger.

  Guaranteed not to block or break the main storage path if it fails [cite: 4, 5,
  11].
  """
  try:
    # Simulate flaky external email service
    # raise Exception("SMTP connection timeout")
    print(
        f"SIDE EFFECT: Confirmation email sent for submission"
        f" {submission_data['email']}"
    )
  except Exception as e:
    # Log error but suppress exception so response succeeds
    print(f"WARNING: Side effect failed safely: {e}")


# 5. Endpoints
@app.get("/widgets/{widget_id}/config")
async def get_widget_config(widget_id: str, response: Response):
  """Public cached widget configuration endpoint[cite: 3, 4, 5]."""
  widget = WIDGET_DB.get(widget_id)
  if not widget:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Widget not found"
    )

  # Set caching headers as required for CDN-like delivery[cite: 3, 5, 11]
  response.headers["Cache-Control"] = "public, max-age=300, s-maxage=600"
  return widget


@app.post("/submissions", status_code=status.HTTP_201_CREATED)
async def create_submission(payload: SubmissionPayload, request: Request):
  """Hardened public submission API handling CORS, validation, spam checks, geo

  enrichment, and safe side effects[cite: 3, 4, 5].
  """
  # Step A: Spam control - Honeypot check[cite: 5, 11]
  if payload.honeypot.strip():
    # Silently drop or reject bot submissions
    return {
        "status": "success",
        "message": "Submission received",
    }  # Return 201 to fool bots, or raise 400

  # Step B: Verify widget existence
  widget = WIDGET_DB.get(payload.widget_id)
  if not widget:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Invalid widget ID"
    )

  # Step C: Extract client IP for geo enrichment
  client_ip = request.client.host if request.client else "127.0.0.1"
  geo_data = await enrich_with_geo(client_ip)

  # Step D: Store submission safely linked to tenant[cite: 4, 5, 9]
  submission_record = {
      "widget_id": payload.widget_id,
      "tenant_id": widget["tenant_id"],
      "name": payload.name,
      "email": payload.email,
      "message": payload.message,
      "geo": geo_data,
  }
  SUBMISSIONS_DB.append(submission_record)

  # Step E: Trigger non-blocking safe side effect[cite: 4, 5, 11]
  await trigger_safe_side_effect(submission_record)

  return {
      "status": "success",
      "message": "Lead captured successfully",
      "data": submission_record,
  }