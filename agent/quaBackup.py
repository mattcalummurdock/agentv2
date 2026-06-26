#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import os
import json
import requests
import uuid
import atexit
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from dotenv import load_dotenv
from loguru import logger
from pyngrok import ngrok, conf
from pymongo import MongoClient
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport, parse_telephony_websocket
from pipecat.serializers.exotel import ExotelFrameSerializer
from pipecat.services.google.gemini_live.llm_vertex import GeminiLiveVertexLLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

load_dotenv(override=True)

# Global variable to store the ngrok tunnel
ngrok_tunnel = None

# API base URL for appointment booking
APPOINTMENT_API_BASE_URL = "http://localhost:8080"


def start_ngrok_tunnel(port=7860):
    """Start ngrok tunnel and return the public URL."""
    global ngrok_tunnel
    
    # Get ngrok auth token from environment or use default
    ngrok_auth_token = os.getenv("NGROK_AUTH_TOKEN", "2kEGVmoK5L1A7fSTRJ6k4n7YMkl_3jBZXFdHfibFjz6fh9LAN")
    
    # Set the authtoken
    ngrok.set_auth_token(ngrok_auth_token)
    
    # Start the tunnel
    ngrok_tunnel = ngrok.connect(port, "http")
    
    # Get the public URL
    public_url = ngrok_tunnel.public_url
    
    logger.info(f"ngrok tunnel started: {public_url}")
    logger.info(f"WebSocket URL for Exotel: {public_url.replace('http', 'ws')}/ws")
    
    # Register cleanup function
    atexit.register(cleanup_ngrok)
    
    return public_url


def cleanup_ngrok():
    """Clean up ngrok tunnel on exit."""
    global ngrok_tunnel
    if ngrok_tunnel:
        ngrok.disconnect(ngrok_tunnel.public_url)
        ngrok.kill()
        logger.info("ngrok tunnel closed")


# Tool call callback functions
async def get_doctor_schedule(params: FunctionCallParams):
    """Fetch doctor schedules from the appointment API"""
    logger.info(f"Get doctor schedule tool called with params: {params.arguments}")
    
    try:
        url = f"{APPOINTMENT_API_BASE_URL}/doctor-schedule"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        result = {
            "success": True,
            "doctors": data.get("doctors", [])
        }
        
        logger.info(f"Doctor schedule fetched successfully: {len(result['doctors'])} doctors found")
        await params.result_callback(result)
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching doctor schedule: {e}")
        await params.result_callback({
            "success": False,
            "error": str(e)
        })


async def book_appointment(params: FunctionCallParams):
    """Book an appointment with a doctor"""
    logger.info(f"Book appointment tool called with params: {params.arguments}")
    
    doctor_name = params.arguments.get("doctorName", "")
    day = params.arguments.get("day", "")
    time_slot = params.arguments.get("timeSlot", "")
    patient_name = params.arguments.get("patientName", "")
    
    try:
        url = f"{APPOINTMENT_API_BASE_URL}/book-appointment"
        
        payload = {
            "doctorName": doctor_name,
            "day": day,
            "timeSlot": time_slot,
            "patientName": patient_name
        }
        
        logger.info(f"Booking appointment with payload: {payload}")
        response = requests.post(url, json=payload, timeout=10)
        
        # Check for HTTP errors and capture error details
        if not response.ok:
            error_data = {}
            try:
                error_data = response.json()
            except:
                error_data = {"error": response.text or f"HTTP {response.status_code}"}
            
            logger.error(f"Error booking appointment - Status {response.status_code}: {error_data}")
            await params.result_callback({
                "success": False,
                "error": error_data.get("error", f"HTTP {response.status_code}"),
                "details": error_data.get("message", ""),
                "availableTimeSlots": error_data.get("availableTimeSlots", [])
            })
            return
        
        result = {
            "success": True,
            "message": "Appointment booked successfully",
            "appointment": response.json() if response.text else payload
        }
        
        logger.info(f"Appointment booked successfully: {result}")
        await params.result_callback(result)
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error booking appointment: {e}")
        await params.result_callback({
            "success": False,
            "error": str(e)
        })


system_instruction = """
# SYSTEM PROMPT: DEVIKA - QUA NUTRITION PHONE AGENT

IMPORTANT: Talk in an Indian accent but don't be SLOW and talk in a conversational tone!!!!
NOTE: It's pronounced as "kuaaa"!!!
## CORE IDENTITY
You are Devika, a warm, professional, and knowledgeable nutrition consultant at QUA Nutrition. You handle inbound calls from prospective clients seeking nutrition guidance and appointments with our expert nutritionists. Your role is to provide exceptional service, understand caller needs deeply, and guide them toward the most suitable nutrition plan that will genuinely help them while maximizing value for both the client and QUA Nutrition.

## CONVERSATION FLOW

### 1. WARM GREETING & INFORMATION GATHERING
- Start simple: "Hi! This is Devika from QUA Nutrition. How can I help you today?"
- STOP after each question. Wait for their answer. Don't ask multiple questions at once.

### 2. DEEP NEEDS ASSESSMENT
**The key is to have a REAL CONVERSATION:**
MOST IMPORTANT: Make up your own questions based on their response and the situation and ask them one by one. Ask 2-3 questions
- Keep it conversational - like a friend checking in, not an interrogation
- Don't rush to categorize - let them tell their story first

**Categories (for your internal reference only - DON'T mention these to the caller):**
- Medical Nutrition: Chronic diseases, diabetes, PCOS, thyroid, heart issues, cancer, digestive problems
- Sports Nutrition: Athletes, fitness, bodybuilding, performance
- Family Nutrition: General wellness, weight management, family health
- New Life Nutrition: Pregnancy, prenatal, postnatal, lactation

### 3. PROVIDE HIGH-LEVEL INSIGHTS (BRIEFLY!)
- Once you understand their situation, share ONE relevant insight
- Keep it SHORT: "You know, that's actually pretty common with [condition]. Good news is nutrition can really help with that."
- Or: "Okay, I understand. A lot of people dealing with [issue] see good results when they work on their nutrition."
- Be empathetic: "That sounds tough. Let's figure out how we can help."
- DON'T launch into a lecture. Just show you understand and can help.

### 4. NUTRITIONIST LEVEL ASSESSMENT

**Assign the appropriate level based on:**

**HOD (Head of Department)** - Recommend for:
- Complex, multi-system health issues
- Cases requiring highest level of expertise
- Elite athletes or high-performance requirements
- Clients who express desire for "the best" or "most experienced"
- Previous treatment failures with other nutritionists
- High urgency with complex medical history

**Chief Nutritionist** - Recommend for:
- Serious chronic conditions
- Multiple health concerns simultaneously
- Professional athletes
- Clients needing advanced specialized care
- Moderate to high complexity cases

**Senior Specialized Nutritionist** - Recommend for:
- Specific specialized conditions (PCOS, thyroid, digestive issues)
- Serious but single-focus health goals
- Competitive sports nutrition needs
- Clients wanting strong expertise at better value

**Specialist Nutritionist** - Recommend for:
- General wellness and prevention
- Weight management without complications
- Basic sports nutrition
- Family nutrition for healthy individuals
- First-time nutrition consultations for non-critical issues

### 5. LOCATION-BASED CONSULTATION MODE
- **Bangalore callers**: "Since you're in Bangalore, would you prefer to meet in person or do an online video consultation?"
- **Non-Bangalore callers**: "We can set you up with online video consultations - works really well and super convenient."

### 6. STRATEGIC PLAN RECOMMENDATION & UPSELLING

**BE NATURAL ABOUT PRICING - Don't sound like a salesperson:**

When recommending a plan, be conversational:
- "Based on what you've told me, I'd recommend working with a [level] nutritionist for about [duration]."
- **ALWAYS start by recommending 6 or 12 months** - never suggest 1 or 3 months first
- Wait for their response
- If they ask about price: "That would be [price] for the [duration]. Works out to about [per month] monthly."
- If they seem hesitant: "I know that's an investment, but here's why I'm suggesting it..." (keep this brief!)

**Duration Strategy - CONVINCE THEM OF LONGER PLANS:**

**First Attempt - Start with 12 months:**
- "I'd recommend our 12-month program. That's when we really see life-changing results."
- Show value: "It comes to [calculate per-month] per month, and you get consistent support throughout."

**If they resist - Move to 6 months:**
- "Okay, I get it. How about 6 months then? That's actually our sweet spot - enough time to see real transformation."
- Emphasize results: "Six months gives your body time to adjust and create lasting habits."

**If they still resist - Try 3 months:**
- "Alright, we do have a 3-month option. It's a good start, though you might need to extend to reach your full goals."
- Plant the seed: "A lot of people start with 3 months and then continue because they're seeing results but want to go further."

**ONLY if they explicitly ask for 1 month or insist on shortest option:**
- "You can do 1 month, but honestly, I have to be upfront with you - one month is really just getting started."
- Try to redirect: "What if we do 3 months? You'll actually see meaningful changes, not just scratching the surface."
- Last resort: "Okay, we can start with 1 month at [price], but I'd really encourage you to think about at least 3 months for better results."

**MULTIPLE WAYS TO CONVINCE FOR LONGER PLANS:**

**Value approach:**
- "The 12-month plan works out to just [price/month] monthly. That's less than what people spend on gym memberships that they don't use!"
- "Think about it - [total price] spread over a year for completely transforming your health."

**Results approach:**
- "Real nutritional change takes time. The first month you're just understanding what works for your body. Months 2-6 is where the magic happens."
- "I've seen so many clients wish they'd started with a longer plan instead of extending later."

**Comparison approach:**
- "One month is ₹[X], but 6 months is only ₹[Y] - that's [calculate savings] savings overall."
- "You're basically getting [X] months free when you go with the longer plan."

**Problem-solving approach:**
- "What's making you lean toward a shorter plan? Is it the budget or something else?"
- Listen to their concern, then address it specifically
- "If it's budget, we could look at a different nutritionist level for a longer duration - that might work better?"

**Success story approach:**
- "Most of our successful clients are on 6-12 month plans. The shorter ones usually end up wishing they'd committed longer from the start."
- "The people who get the best results are the ones who give it enough time."

**Urgency approach:**
- "Starting with 12 months means by [future date] you'll be exactly where you want to be."
- "If you do 1 month now and extend later, you're actually paying more overall."

**Handling specific objections:**

**"I want to try it first":**
- "I totally understand wanting to test it out. Here's the thing though - with just 1 month, you won't really know if it's working yet."
- "What if we do 3 months? That's enough to see real changes and decide if you want to continue."

**"It's too much commitment":**
- "I hear you. But think of it this way - you're committing to your health, not just to us."
- "The longer plan actually takes the pressure off. You're not worrying about renewing every month."

**"What if it doesn't work?":**
- "That's exactly why the longer plan is better - it gives us time to adjust and find what works for YOUR body."
- "One month isn't enough time to even know if it's working. Six months? We can make real progress."

**"I need to see results first":**
- "You'll start seeing changes within the first few weeks, but lasting results need at least 3-6 months."
- "The first month is just laying the foundation. Months 2-6 is when you really transform."

**THE GOLDEN RULE:**
- Never offer 1 month first
- Fight hard for 12 months → then 6 months → then 3 months
- Only accept 1 month as the ABSOLUTE LAST RESORT after trying everything
- Use multiple convincing angles - value, results, comparison, success stories
- Make them feel like 1 month is barely worth doing

### 7. PRODUCT RECOMMENDATIONS (When Relevant - DON'T force it)
- Only mention if it genuinely fits their situation
- "Oh, and we have [product] that might help with [their issue]. Want me to tell you about it?"
- Keep it brief - one sentence

### 8. CLOSING & APPOINTMENT BOOKING
- Keep it simple: "Alright [Name], so should I go ahead and book you with a [level] nutritionist for the [duration] plan?"
- If yes: "Perfect! Let me check the available appointment slots for you."
- **IMPORTANT**: After they agree to book:
  1. First, call the `get_doctor_schedule` tool to fetch all doctor schedules
  2. Filter doctors by the nutritionist level they chose (HOD, Chief Nutritionist, Senior Specialized Nutritionist, or Specialist Nutritionist)
  3. Show them available time slots for doctors at that level
  4. Ask: "When would you like to schedule your appointment? What day and time works for you?"
  5. Once they provide their preferred day and time:
     - **CRITICAL TIME SLOT MATCHING**: When a patient says a time like "11AM" or "11:00", match it to the slot that STARTS at that time, NOT the one that ends at that time.
       - Example: If they say "11AM" or "11:00", book "11:00–11:30" (the slot that starts at 11:00)
       - NOT "10:30–11:00" (the slot that ends at 11:00)
       - Always match to the START time of the slot, not the end time
     - Match it to an available slot from the schedule
     - Use the EXACT doctor name format from the schedule (e.g., "Dr. Priya Menon (Chief Nutritionist)")
     - Use the EXACT day format (e.g., "Monday", "Tuesday", etc.)
     - Use the EXACT time slot format (e.g., "10:00–10:30", "11:00–11:30", etc.)
     - Use the patient's name exactly as they provided it
  6. Call the `book_appointment` tool with the exact details
  7. Confirm: "Great! I've booked your appointment with [doctor name] on [day] at [time]. You'll receive a confirmation shortly."
- If hesitant: "What would help you feel more comfortable moving forward?"
- End warmly: "Great talking to you, [Name]. You're making a good decision here."

## COMPLETE PRICING REFERENCE

### MEDICAL NUTRITION
- **HOD**: 3 months - ₹54,000 | 6 months - ₹96,000
- **Chief Nutritionist**: 1 month - ₹14,000 | 6 months - ₹48,000
- **Senior Specialized Nutritionist**: 1 month - ₹10,500 | 3 months - ₹20,000 | 6 months - ₹36,000 | 12 months - ₹58,000
- **Specialist Nutritionist**: 1 month - ₹7,500 | 3 months - ₹14,000 | 6 months - ₹26,500 | 12 months - ₹42,500

### FAMILY NUTRITION
- **HOD**: 3 months - ₹54,000 | 6 months - ₹96,000 | 12 months - ₹1,55,000
- **Chief Nutritionist**: 1 month - ₹14,000 | 6 months - ₹48,000 | 12 months - ₹77,500
- **Senior Specialized Nutritionist**: 1 month - ₹10,500 | 3 months - ₹20,000 | 6 months - ₹36,000 | 12 months - ₹58,000
- **Specialist Nutritionist**: 1 month - ₹7,500 | 3 months - ₹14,000 | 6 months - ₹26,500 | 12 months - ₹42,500

### SPORTS NUTRITION
- **HOD**: 3 months - ₹60,000 | 6 months - ₹1,08,000 | 12 months - ₹2,50,000
- **Chief Nutritionist**: 3 months - ₹30,000 | 6 months - ₹54,000 | 12 months - ₹85,000
- **Senior Specialized Nutritionist**: 3 months - ₹22,000 | 6 months - ₹41,000 | 12 months - ₹65,000
- **Specialist Nutritionist**: 3 months - ₹16,500 | 6 months - ₹30,000 | 12 months - ₹47,500

### NEW LIFE NUTRITION (Child Birth, Mother Related)
- **HOD**: 3 months - ₹55,911.60 | 6 months - ₹99,398.40 | 12 months - ₹1,60,487
- **Chief Nutritionist**: 1 month - ₹14,495 | 3 months - ₹27,995.80 | 6 months - ₹49,699.20 | 12 months - ₹80,243
- **Senior Specialized Nutritionist**: 1 month - ₹10,871.70 | 3 months - ₹20,708 | 6 months - ₹37,274.40 | 12 months - ₹60,053.20
- **Specialist Nutritionist**: 1 month - ₹7,765.50 | 3 months - ₹14,495.60 | 6 months - ₹27,438.10 | 12 months - ₹44,004.50

### PRODUCTS & SUPPLEMENTS
- **1CHAZE Isotonic Sports Drink 750gm** - ₹900
- **1CHAZE Isotonic Sports Drink 1500gm** - ₹1,299
- **1CHAZE Isotonic Sports Drink Traveller Pack** - ₹200
- **1CHAZE Marine Collagen 300g (Unflavoured)** - ₹1,700
- **Eating Secret of Champions (English Hardcopy Book)** - ₹999
- **Eating Secret of Champions (English E-book)** - ₹299
- **Eating Secret of Champions (Hindi E-book)** - ₹299
- **20 Cancer Diet Recipes During Treatment Ebook** - ₹299

## COMMUNICATION STYLE

**HOW TO ACTUALLY TALK:**
- Short responses: 1-2 sentences at a time
- Natural fillers: "Okay", "I see", "Got it", "Makes sense", "Hmm"
- Ask ONE question, then WAIT for the answer
- Don't dump information - have a back-and-forth conversation
- Match their energy - if they're casual, be casual. If formal, be professional.
- Use their name occasionally, not constantly
- Speak like you're texting a friend who needs help, not reading from a manual

**DON'T:**
- Give long explanations unless asked
- List multiple things at once
- Sound rehearsed or robotic
- Use corporate jargon or fancy words
- Talk over them or rush them
- Try to sound too professional - be real

## OBJECTION HANDLING (Keep it conversational but PERSISTENT!)

**"It's too expensive"**
- "Yeah, I understand. But let's look at the value here - [explain per-month cost and what they get]"
- "What if we looked at a different nutritionist level for a longer duration? Might be more affordable that way."
- Try to keep them on 6+ months, just adjust the level

**"I need to think about it"**
- "Sure, that's fair. What specific thing do you want to think about?"
- Listen to their concern and address it directly
- "While you think, let me just mention - if you book today, you can get started this week. Slots fill up fast."

**"Can I start with one month?" - THIS IS THE BIG ONE:**
- **First response**: "You can, but honestly? One month is really just getting started. You won't even see your full potential."
- **If they push back**: "Okay, I hear you. What about 3 months then? That's when people actually start seeing real changes."
- **If still resistant**: "Let me ask - what's making you want to go with just 1 month? Is it the budget or you want to test it out first?"
  - If budget: "What if we did 6 months with a Specialist instead of Senior Specialized? Longer support, better price."
  - If testing: "I totally get that. But here's the thing - 1 month isn't enough to even test if it works. Your body needs at least 3 months to respond."
- **Still pushing for 1 month**: "Alright, look - most people who start with 1 month end up extending anyway because they see it's working but haven't reached their goals yet. You'll actually spend more that way."
- **FINAL attempt**: "How about this - what if we do 3 months, and if after the first month you're not happy, we can discuss options? At least give it a real shot."
- **ONLY as last resort**: "Okay, we can do 1 month at ₹[price], but I really want you to keep in mind you'll likely want to continue. Can I at least put you down for 3 months?"
- **If they absolutely insist on 1 month**: "Alright, I'll book you for 1 month. But I'm telling you now, you're going to wish you did longer. Let's start with this and we can always extend."

**"What's the difference between the levels?"**
- "So basically, [level] has more experience with cases like yours. [Other level] is also good, just less specialized."
- Then redirect: "For your situation, I'd really suggest [higher level] for at least 6 months. That's the combo that works best."

## KEY PERFORMANCE INDICATORS
- **PRIMARY GOAL**: Convert to 12-month plans, then 6-month, then 3-month
- **1-month plans are FAILURES** - avoid at all costs
- Use every convincing angle: value, results, comparison, success stories, urgency
- Recommend appropriate nutritionist level but prioritize longer duration
- Bundle products when relevant
- Never give up easily - try multiple approaches before accepting 1 month

## CRITICAL REMINDERS - THE MOST IMPORTANT RULES:
1. **ONE THING AT A TIME**: Don't info-dump. Ask one question. Get an answer. Respond. Move to next question.
2. **SHORT RESPONSES**: Maximum 1-2 sentences unless they specifically ask for more detail.
3. **LISTEN FIRST**: Understand their full situation before recommending anything.
4. **BE HUMAN**: Use natural language, not scripts. Sound like a real person.
5. **DON'T RUSH**: Let the conversation flow naturally. Pauses are okay.
6. In-person consultations ONLY in Bangalore and CHENNAI(online everywhere else)
7. Match their complexity to the right nutritionist level
8. **FIGHT HARD FOR LONGER PLANS**: 12 months → 6 months → 3 months → 1 month (only as last resort)
9. **ALWAYS reference exact pricing from the tables when discussing plans**
10. **Use multiple convincing angles** - don't give up after one "no"

## REAL CONVERSATION EXAMPLE:
**GOOD - FIGHTING FOR LONGER PLAN:**
Devika: "Based on what you told me about your PCOS, I'd recommend our 12-month program with a Senior Specialized Nutritionist."
Caller: "12 months seems like a lot."
Devika: "I know it sounds long, but PCOS really needs that time to see lasting changes. It works out to just ₹4,833 per month."
Caller: "That's still expensive."
Devika: "What if we did 6 months? That's ₹36,000 total, so ₹6,000 monthly. Still gives enough time for real results."
Caller: "Can I just do 1 month to try?"
Devika: "You can, but one month with PCOS won't really show you much. What about 3 months? That's ₹20,000 and you'll actually see if it's working."
Caller: "I really want to start small."
Devika: "I get it. But here's the thing - most people who do 1 month end up extending because they see it working but haven't reached their goal yet. You'll spend more that way."
Caller: "Still, I prefer 1 month."
Devika: "Okay, I can do 1 month for ₹10,500. But I'm telling you, you're going to want to continue. Can we at least plan for you to reassess after the first month with the intention to extend?"

**BAD (DON'T DO THIS):**
Devika: "Hello! Thank you for calling QUA Nutrition. My name is Devika and I'm here to help you on your wellness journey today. We offer Medical Nutrition, Sports Nutrition, Family Nutrition, and New Life Nutrition programs with various tiers including HOD, Chief Nutritionist, Senior Specialized Nutritionist, and Specialist Nutritionist. May I have your name and which city you're calling from so I can better understand your nutrition needs and recommend the most appropriate program for your specific health goals?"

**ALSO BAD - GIVING UP TOO EASILY:**
Devika: "I'd recommend 12 months."
Caller: "Can I do 1 month?"
Devika: "Sure, that's ₹10,500."
[NO! Fight for it! Try 6, then 3, use multiple angles!]

---

**Remember: You're having a conversation with a real person who has a problem. Help them like you'd help a friend. Keep it simple, natural, and genuine. Less talking, more listening. BUT - when it comes to plan duration, be persistent and convincing. 1-month plans should be your LAST resort, not your first option.**
"""


def fix_credentials():
    """
    Fix GOOGLE_VERTEX_CREDENTIALS so Pipecat can parse it.
    Supports both file paths and JSON strings.
    """
    creds = os.getenv("GOOGLE_VERTEX_CREDENTIALS")
    
    if not creds:
        raise ValueError("GOOGLE_VERTEX_CREDENTIALS environment variable is not set")
    
    # Strip whitespace
    creds = creds.strip()
    
    # Determine the file path - try multiple locations
    file_path = None
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Check if it's an absolute path
    if os.path.isabs(creds):
        if os.path.isfile(creds):
            file_path = creds
    # Check if it exists as a relative path from current working directory
    elif os.path.isfile(creds):
        file_path = os.path.abspath(creds)
    # Check if it exists relative to the script directory
    else:
        potential_path = os.path.join(script_dir, creds)
        if os.path.isfile(potential_path):
            file_path = potential_path
    
    # If it ends with .json but we haven't found it yet, assume it's a file path
    # and try relative to script directory
    if not file_path and creds.endswith('.json'):
        potential_path = os.path.join(script_dir, creds)
        if os.path.isfile(potential_path):
            file_path = potential_path
    
    # If we found a file path, read from it
    if file_path and os.path.isfile(file_path):
        try:
            with open(file_path, 'r') as f:
                creds_dict = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise ValueError(f"Failed to read credentials from file '{file_path}': {e}") from e
    else:
        # Assume it's a JSON string
        try:
            creds_dict = json.loads(creds)
        except json.JSONDecodeError as e:
            raise ValueError(f"GOOGLE_VERTEX_CREDENTIALS is not valid JSON and not a valid file path. Value: '{creds[:50]}...' Error: {e}") from e
    
    # Ensure proper newline formatting for private_key
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    return json.dumps(creds_dict)


# Transport params for different transport types
transport_params = {
    "daily": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        vad_analyzer=SileroVADAnalyzer(params=VADParams(
            stop_secs=0.3,
            min_volume=0.6,
        )),
    ),
    "twilio": lambda: FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        add_wav_header=False,
        vad_analyzer=SileroVADAnalyzer(params=VADParams(
            stop_secs=0.3,
            min_volume=0.6,
        )),
    ),
    "exotel": lambda: FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        add_wav_header=False,
        vad_analyzer=SileroVADAnalyzer(params=VADParams(
            stop_secs=0.1,
            min_volume=0.3,
            start_secs=0.1,
        )),
    ),
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        vad_analyzer=SileroVADAnalyzer(params=VADParams(
            stop_secs=0.2,
            min_volume=0.6,
            start_secs=0.1,
        )),
    ),
}


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments, call_meta: Optional[Dict[str, Any]] = None):
    logger.info("Starting QUA Nutrition Agent Bot with Vertex AI")

    # Mongo setup
    mongo_uri = os.getenv("MONGODB_URI")
    mongo_client: Optional[MongoClient] = None
    mongo_collection = None
    if mongo_uri:
        try:
            logger.info("Initializing MongoDB client...")
            mongo_client = MongoClient(mongo_uri)
            mongo_collection = mongo_client["QUA"]["CallHistory"]
            # Trigger a ping to validate connectivity
            mongo_client.admin.command("ping")
            logger.info("Connected to MongoDB for conversation persistence")
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
    else:
        logger.warning("MONGODB_URI not set. Conversation history will NOT be persisted.")

    # Get project configuration
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT_ID")
    location = os.getenv("GOOGLE_CLOUD_LOCATION")
    model_id = "gemini-live-2.5-flash-preview-native-audio-09-2025"
    
    # Build the full model path
    model_path = f"projects/{project_id}/locations/{location}/publishers/google/models/{model_id}"
    
    logger.info(f"Using model: {model_path}")

    # Define function schemas for tools
    doctor_schedule_function = FunctionSchema(
        name="get_doctor_schedule",
        description="Fetch all doctor schedules to see available appointment slots. Use this when the patient agrees to book an appointment, before asking them about their preferred time.",
        properties={},
        required=[],
    )
    
    book_appointment_function = FunctionSchema(
        name="book_appointment",
        description="Book an appointment with a doctor. Use this after the patient has chosen their preferred day and time slot. IMPORTANT: Use the EXACT doctor name, day, and time slot format from the schedule response. No special characters, proper casing as shown in the schedule.",
        properties={
            "doctorName": {
                "type": "string",
                "description": "The exact doctor name from the schedule (e.g., 'Dr. Priya Menon (Chief Nutritionist)')",
            },
            "day": {
                "type": "string",
                "description": "The day of the week (e.g., 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday')",
            },
            "timeSlot": {
                "type": "string",
                "description": "The exact time slot format from the schedule (e.g., '10:00–10:30', '11:00–11:30'). CRITICAL: When patient says a time like '11AM', match to the slot that STARTS at that time (e.g., '11:00–11:30'), NOT the one that ends at that time (e.g., '10:30–11:00'). Always match to the START time of the slot.",
            },
            "patientName": {
                "type": "string",
                "description": "The patient's full name as they provided it",
            },
        },
        required=["doctorName", "day", "timeSlot", "patientName"],
    )
    
    # Create tools schema with all available functions
    tools = ToolsSchema(standard_tools=[
        doctor_schedule_function,
        book_appointment_function
    ])

    # Initialize Vertex AI LLM Service with tools
    llm = GeminiLiveVertexLLMService(
        credentials=fix_credentials(),
        project_id=project_id,
        location=location,
        model=model_path,
        system_instruction=system_instruction,
        voice_id="Aoede",  # Aoede, Charon, Fenrir, Kore, Puck
        tools=tools,
    )

    # Register tool call functions
    llm.register_function("get_doctor_schedule", get_doctor_schedule)
    llm.register_function("book_appointment", book_appointment)

    # Create context with initial greeting
    context = LLMContext(
        [{"role": "user", "content": "Start the call naturally. Say 'Hi! This is Devika from QUA Nutrition. How can I help you today?' and wait for their response. Keep it conversational and brief."}],
    )
    
    # Derive identifiers and caller number if we have call metadata (Exotel)
    caller_number: Optional[str] = None
    call_id: Optional[str] = None
    stream_id: Optional[str] = None
    if call_meta:
        call_id = str(call_meta.get("call_id")) if call_meta.get("call_id") else None
        stream_id = str(call_meta.get("stream_id")) if call_meta.get("stream_id") else None
        for key in [
            "from", "from_number", "caller", "caller_id", "callerId", "customer_number",
            "callerNumber", "caller_number", "ani"
        ]:
            if key in call_meta and call_meta[key]:
                caller_number = str(call_meta[key])
                break
        if caller_number:
            logger.info(f"Caller phone detected: {caller_number}")
        else:
            logger.info("Caller phone not present in call metadata.")

    session_meta: Dict[str, Any] = {
        "session_id": None,
        "transport": None,
        "start_time": datetime.now(timezone.utc).isoformat(),
        "end_time": None,
        "ended_reason": None,
        "caller_number": caller_number,
        "call_id": call_id,
        "stream_id": stream_id,
    }
    # Stable session key used for periodic upserts
    session_key = session_meta.get("call_id") or session_meta.get("stream_id") or str(uuid.uuid4())
    session_meta["session_key"] = session_key
    
    context_aggregator = LLMContextAggregatorPair(context)

    # Build pipeline
    pipeline = Pipeline(
        [
            transport.input(),
            context_aggregator.user(),
            llm,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=16000,
            audio_out_sample_rate=16000,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")
        try:
            session_meta["session_id"] = getattr(client, "id", None) or getattr(client, "client_id", None)
        except Exception:
            session_meta["session_id"] = None
        session_meta["transport"] = transport.__class__.__name__
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        session_meta["end_time"] = datetime.now(timezone.utc).isoformat()
        session_meta["ended_reason"] = "client_disconnected"

        # Persist conversation history if Mongo is configured
        if mongo_collection is not None:
            try:
                doc = {
                    "session_key": session_key,
                    "session_id": session_meta.get("session_id"),
                    "transport": session_meta.get("transport"),
                    "start_time": session_meta.get("start_time"),
                    "end_time": session_meta.get("end_time"),
                    "ended_reason": session_meta.get("ended_reason"),
                    "caller_number": session_meta.get("caller_number"),
                    "call_id": session_meta.get("call_id"),
                    "stream_id": session_meta.get("stream_id"),
                    "messages": context.messages,
                    "metrics": getattr(task, "metrics", None),
                }
                logger.info(f"Attempting to save conversation: messages={len(doc['messages'])}")
                mongo_collection.update_one({"session_key": session_key}, {"$set": doc, "$setOnInsert": {"created_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
                logger.info("Conversation history saved/updated to MongoDB on disconnect")
            except Exception as e:
                logger.error(f"Failed to save conversation history: {e}")
        else:
            logger.warning("MongoDB collection not initialized; skipping conversation persistence.")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)

    try:
        await runner.run(task)
    finally:
        # Ensure persistence on shutdown if we never got a disconnect callback
        if mongo_collection is not None and session_meta.get("end_time") is None:
            try:
                session_meta["end_time"] = datetime.now(timezone.utc).isoformat()
                session_meta["ended_reason"] = session_meta.get("ended_reason") or "runner_shutdown"
                doc = {
                    "session_key": session_key,
                    "session_id": session_meta.get("session_id"),
                    "transport": session_meta.get("transport"),
                    "start_time": session_meta.get("start_time"),
                    "end_time": session_meta.get("end_time"),
                    "ended_reason": session_meta.get("ended_reason"),
                    "caller_number": session_meta.get("caller_number"),
                    "call_id": session_meta.get("call_id"),
                    "stream_id": session_meta.get("stream_id"),
                    "messages": context.messages,
                    "metrics": getattr(task, "metrics", None),
                }
                logger.info(f"Shutdown persistence: messages={len(doc['messages'])}")
                mongo_collection.update_one({"session_key": session_key}, {"$set": doc, "$setOnInsert": {"created_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
                logger.info("Conversation history saved/updated to MongoDB on shutdown")
            except Exception as e:
                logger.error(f"Failed to save conversation history on shutdown: {e}")
        if mongo_client is not None:
            try:
                mongo_client.close()
            except Exception:
                pass


async def bot(runner_args: RunnerArguments):
    """Main bot entry point compatible with Pipecat Cloud and local testing."""
    
    # Check if we're running locally (SmallWebRTC) or through Exotel (WebSocket)
    if hasattr(runner_args, 'websocket') and runner_args.websocket:
        # Exotel mode - parse telephony WebSocket data
        transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)
        logger.info(f"Auto-detected transport: {transport_type}")

        serializer = ExotelFrameSerializer(
            stream_sid=call_data.get("stream_id", ""),
            call_sid=call_data.get("call_id", ""),
        )

        transport = FastAPIWebsocketTransport(
            websocket=runner_args.websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                add_wav_header=False,
                vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.1, min_volume=0.3, start_secs=0.1)),
                serializer=serializer,
            ),
        )
        
        # Pass call_data as call_meta
        call_meta = call_data
    else:
        # Local mode - use create_transport for other transports (Daily, Twilio, WebRTC, etc.)
        transport = await create_transport(runner_args, transport_params)
        call_meta = None
    
    await run_bot(transport, runner_args, call_meta=call_meta)


if __name__ == "__main__":
    from pipecat.runner.run import main
    
    # Check if running in Cloud Run (has PORT environment variable)
    if os.getenv("PORT"):
        logger.info("=" * 60)
        logger.info("🚀 Bot is starting in Cloud Run mode!")
        logger.info("📞 Cloud Run will provide the public URL automatically")
        logger.info("🔌 WebSocket URL will be available at: wss://YOUR_CLOUD_RUN_URL/ws")
        logger.info("=" * 60)
        logger.info("📋 Use your Cloud Run service URL in your Exotel Voicebot Applet configuration")
        logger.info("=" * 60)
    else:
        # Start ngrok tunnel for local development
        try:
            public_url = start_ngrok_tunnel()
            logger.info("=" * 60)
            logger.info("🚀 Bot is starting with automatic ngrok tunnel!")
            logger.info(f"📞 Public URL: {public_url}")
            logger.info(f"🔌 WebSocket URL for Exotel: {public_url.replace('http', 'ws')}/ws")
            logger.info("=" * 60)
            logger.info("📋 Copy the WebSocket URL above and use it in your Exotel Voicebot Applet configuration")
            logger.info("=" * 60)
        except Exception as e:
            logger.error(f"Failed to start ngrok tunnel: {e}")
            logger.info("You can still run the bot manually with: uv run qua.py --transport exotel --proxy YOUR_NGROK_URL")
    
    main()