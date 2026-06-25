"""
Google Calendar Easy Connector - Enhanced with Organization Access
Supports both personal OAuth and organization-wide service account access
"""

from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import os.path
import pickle
import json


class CalendarConnector:
    """Easy-to-use Google Calendar connector with organization support"""
    
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    
    def __init__(self, credentials_file='OAuth.json', token_file='token.pickle', 
                 service_account_file=None, delegated_user=None):
        """
        Initialize the calendar connector
        
        Args:
            credentials_file: Path to OAuth2 credentials JSON (for personal use)
            token_file: Path to store authentication token
            service_account_file: Path to service account JSON (for org-wide access)
            delegated_user: Email of user to impersonate (required with service account)
        """
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service_account_file = service_account_file
        self.delegated_user = delegated_user
        self.service = None
        self.current_user = delegated_user
        
        self._authenticate()
    
    def _authenticate(self):
        """Handle authentication - either OAuth or Service Account"""
        if self.service_account_file:
            self._authenticate_service_account()
        else:
            self._authenticate_oauth()
    
    def _authenticate_oauth(self):
        """Handle OAuth authentication for personal use"""
        creds = None
        
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as token:
                creds = pickle.load(token)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, self.SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open(self.token_file, 'wb') as token:
                pickle.dump(creds, token)
        
        self.service = build('calendar', 'v3', credentials=creds)
    
    def _authenticate_service_account(self):
        """Handle service account authentication for org-wide access"""
        if not self.delegated_user:
            raise ValueError("delegated_user email is required when using service account")
        
        credentials = service_account.Credentials.from_service_account_file(
            self.service_account_file,
            scopes=self.SCOPES,
            subject=self.delegated_user
        )
        
        self.service = build('calendar', 'v3', credentials=credentials)
    
    def switch_user(self, user_email):
        """
        Switch to a different user's calendar (only works with service account)
        
        Args:
            user_email: Email of the user whose calendar to access
        """
        if not self.service_account_file:
            raise ValueError("User switching only available with service account authentication")
        
        self.delegated_user = user_email
        self.current_user = user_email
        self._authenticate_service_account()
    
    def get_events(self, max_results=10, days_ahead=7, calendar_id='primary'):
        """
        Get upcoming events
        
        Args:
            max_results: Maximum number of events to return
            days_ahead: Number of days to look ahead
            calendar_id: Calendar ID (default: 'primary', or use email for specific user)
            
        Returns:
            List of event dictionaries
        """
        now = datetime.utcnow().isoformat() + 'Z'
        end_time = (datetime.utcnow() + timedelta(days=days_ahead)).isoformat() + 'Z'
        
        events_result = self.service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            timeMax=end_time,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        return events_result.get('items', [])
    
    def get_events_in_timeframe(self, minutes_from_now_start=0, minutes_from_now_end=60, 
                                max_results=50, calendar_id='primary'):
        """
        Get events in a specific timeframe (in minutes from now)
        
        Args:
            minutes_from_now_start: Start of timeframe in minutes from now
            minutes_from_now_end: End of timeframe in minutes from now
            max_results: Maximum number of events to return
            calendar_id: Calendar ID (default: 'primary')
            
        Returns:
            List of event dictionaries
        """
        now = datetime.utcnow()
        start_time = (now + timedelta(minutes=minutes_from_now_start)).isoformat() + 'Z'
        end_time = (now + timedelta(minutes=minutes_from_now_end)).isoformat() + 'Z'
        
        events_result = self.service.events().list(
            calendarId=calendar_id,
            timeMin=start_time,
            timeMax=end_time,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        return events_result.get('items', [])
    
    def filter_events_by_organizer(self, events, organizer_email):
        """
        Filter events where the specified email is the organizer
        
        Args:
            events: List of event dictionaries
            organizer_email: Email address of the organizer to filter by
            
        Returns:
            List of events where organizer_email is the organizer
        """
        filtered_events = []
        
        for event in events:
            # Check if organizer exists and matches
            organizer = event.get('organizer', {})
            if organizer.get('email', '').lower() == organizer_email.lower():
                filtered_events.append(event)
        
        return filtered_events
    
    def get_current_user_email(self):
        """
        Get the email of the currently authenticated user
        
        Returns:
            Email address of the current user
        """
        if self.delegated_user:
            return self.delegated_user
        
        # For OAuth, we need to get the calendar info
        try:
            calendar = self.service.calendars().get(calendarId='primary').execute()
            return calendar.get('id', None)
        except Exception as e:
            print(f"Error getting user email: {e}")
            return None
    
    def get_events_for_user(self, user_email, max_results=10, days_ahead=7):
        """
        Get events for a specific user (service account only)
        
        Args:
            user_email: Email of the user
            max_results: Maximum number of events to return
            days_ahead: Number of days to look ahead
            
        Returns:
            List of event dictionaries
        """
        if not self.service_account_file:
            raise ValueError("This method requires service account authentication")
        
        # Temporarily switch to the user
        original_user = self.current_user
        self.switch_user(user_email)
        
        try:
            events = self.get_events(max_results, days_ahead)
            return events
        finally:
            # Switch back to original user
            if original_user:
                self.switch_user(original_user)
    
    def get_events_for_multiple_users(self, user_emails, max_results=10, days_ahead=7):
        """
        Get events for multiple users (service account only)
        
        Args:
            user_emails: List of user email addresses
            max_results: Maximum number of events per user
            days_ahead: Number of days to look ahead
            
        Returns:
            Dictionary mapping email to list of events
        """
        if not self.service_account_file:
            raise ValueError("This method requires service account authentication")
        
        results = {}
        for email in user_emails:
            try:
                results[email] = self.get_events_for_user(email, max_results, days_ahead)
            except Exception as e:
                results[email] = {'error': str(e)}
        
        return results
    
    def find_free_slots(self, user_emails, duration_minutes=30, days_ahead=7):
        """
        Find common free time slots for multiple users
        
        Args:
            user_emails: List of user email addresses
            duration_minutes: Required duration in minutes
            days_ahead: Number of days to search
            
        Returns:
            List of available time slots
        """
        # Get all events for all users
        all_events = []
        for email in user_emails:
            events = self.get_events_for_user(email, max_results=100, days_ahead=days_ahead)
            all_events.extend(events)
        
        # Find free slots (simplified version - you can enhance this)
        # This is a basic implementation
        free_slots = []
        current_time = datetime.utcnow()
        end_time = current_time + timedelta(days=days_ahead)
        
        # Check each hour slot
        check_time = current_time.replace(minute=0, second=0, microsecond=0)
        while check_time < end_time:
            slot_end = check_time + timedelta(minutes=duration_minutes)
            
            # Check if this slot conflicts with any event
            is_free = True
            for event in all_events:
                event_start = datetime.fromisoformat(
                    event['start'].get('dateTime', event['start'].get('date')).replace('Z', '+00:00')
                )
                event_end = datetime.fromisoformat(
                    event['end'].get('dateTime', event['end'].get('date')).replace('Z', '+00:00')
                )
                
                # Check for overlap
                if (check_time < event_end and slot_end > event_start):
                    is_free = False
                    break
            
            if is_free and check_time > current_time:
                free_slots.append({
                    'start': check_time.isoformat(),
                    'end': slot_end.isoformat()
                })
            
            check_time += timedelta(minutes=30)  # Check every 30 minutes
        
        return free_slots[:20]  # Return first 20 free slots
    
    def create_event(self, summary, start_time, end_time, description=None, 
                    location=None, attendees=None, calendar_id='primary'):
        """
        Create a new calendar event
        
        Args:
            summary: Event title
            start_time: Start time (datetime object or ISO format string)
            end_time: End time (datetime object or ISO format string)
            description: Event description (optional)
            location: Event location (optional)
            attendees: List of attendee emails (optional)
            calendar_id: Calendar ID (default: 'primary')
            
        Returns:
            Created event dictionary
        """
        if isinstance(start_time, datetime):
            start_time = start_time.isoformat()
        if isinstance(end_time, datetime):
            end_time = end_time.isoformat()
        
        event = {
            'summary': summary,
            'start': {'dateTime': start_time, 'timeZone': 'UTC'},
            'end': {'dateTime': end_time, 'timeZone': 'UTC'},
        }
        
        if description:
            event['description'] = description
        if location:
            event['location'] = location
        if attendees:
            event['attendees'] = [{'email': email} for email in attendees]
        
        created_event = self.service.events().insert(
            calendarId=calendar_id,
            body=event,
            sendUpdates='all' if attendees else 'none'
        ).execute()
        
        return created_event
    
    def delete_event(self, event_id, calendar_id='primary'):
        """Delete an event"""
        self.service.events().delete(
            calendarId=calendar_id,
            eventId=event_id
        ).execute()
    
    def update_event(self, event_id, calendar_id='primary', **kwargs):
        """Update an existing event"""
        event = self.service.events().get(
            calendarId=calendar_id,
            eventId=event_id
        ).execute()
        
        if 'summary' in kwargs:
            event['summary'] = kwargs['summary']
        if 'description' in kwargs:
            event['description'] = kwargs['description']
        if 'location' in kwargs:
            event['location'] = kwargs['location']
        if 'start_time' in kwargs:
            start = kwargs['start_time']
            if isinstance(start, datetime):
                start = start.isoformat()
            event['start'] = {'dateTime': start, 'timeZone': 'UTC'}
        if 'end_time' in kwargs:
            end = kwargs['end_time']
            if isinstance(end, datetime):
                end = end.isoformat()
            event['end'] = {'dateTime': end, 'timeZone': 'UTC'}
        
        updated_event = self.service.events().update(
            calendarId=calendar_id,
            eventId=event_id,
            body=event
        ).execute()
        
        return updated_event
    
    def print_events(self, events=None, user_label=None):
        """Pretty print events"""
        if events is None:
            events = self.get_events()
        
        if not events:
            print('No upcoming events found.')
            return
        
        header = f'\nUpcoming {len(events)} events'
        if user_label:
            header += f' for {user_label}'
        header += ':'
        print(header)
        print('-' * 60)
        
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            print(f"• {event['summary']}")
            print(f"  Time: {start}")
            if 'location' in event:
                print(f"  Location: {event['location']}")
            if 'attendees' in event:
                attendees = ', '.join([a.get('email', '') for a in event['attendees']])
                print(f"  Attendees: {attendees}")
            print()



if __name__ == '__main__':

    # Initialize the connector (it will handle authentication automatically)
    calendar = CalendarConnector()

    # Example 1: Get upcoming events
    print("=== Getting Upcoming Events ===")
    events = calendar.get_events(max_results=5)
    calendar.print_events(events)