"""
Quick Setup Verification Script
================================
Run this script to verify your organization calendar access is working correctly.
"""

from client import CalendarConnector
import sys

def verify_setup():
    """Verify that the service account setup is working"""
    
    print("=" * 60)
    print("🔍 Google Calendar Organization Access - Setup Verification")
    print("=" * 60)
    print()
    
    # Step 1: Check for service account file
    print("Step 1: Checking for service-account.json...")
    try:
        with open('service-account.json', 'r') as f:
            import json
            sa_data = json.load(f)
            print(f"  ✅ Found service account: {sa_data.get('client_email', 'Unknown')}")
    except FileNotFoundError:
        print("  ❌ service-account.json not found!")
        print("     Please download your service account key and name it 'service-account.json'")
        print("     See ORG_SETUP_GUIDE.md for instructions")
        return False
    except Exception as e:
        print(f"  ❌ Error reading service account file: {e}")
        return False
    
    print()
    
    # Step 2: Get user email
    print("Step 2: Enter your email (or any user in your organization)")
    user_email = input("  Email: ").strip()
    
    if not user_email or '@' not in user_email:
        print("  ❌ Invalid email address")
        return False
    
    print()
    
    # Step 3: Try to connect
    print("Step 3: Attempting to connect...")
    try:
        calendar = CalendarConnector(
            service_account_file='service-account.json',
            delegated_user=user_email
        )
        print(f"  ✅ Successfully connected as {user_email}")
    except Exception as e:
        print(f"  ❌ Connection failed: {e}")
        print()
        print("Common issues:")
        print("  1. Domain-wide delegation not configured")
        print("  2. Wrong OAuth scope in Google Workspace Admin")
        print("  3. Google Calendar API not enabled")
        print()
        print("Please see ORG_SETUP_GUIDE.md for troubleshooting")
        return False
    
    print()
    
    # Step 4: Try to get events
    print("Step 4: Fetching calendar events...")
    try:
        events = calendar.get_events(max_results=5)
        print(f"  ✅ Successfully retrieved {len(events)} events")
        
        if events:
            print()
            print("  Your upcoming events:")
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                print(f"    • {event['summary']} - {start}")
        else:
            print("  ℹ️  No upcoming events found")
    except Exception as e:
        print(f"  ❌ Failed to retrieve events: {e}")
        return False
    
    print()
    
    # Step 5: Test accessing another user's calendar (optional)
    print("Step 5: Test accessing another user's calendar (optional)")
    other_email = input("  Enter another user's email (or press Enter to skip): ").strip()
    
    if other_email:
        try:
            other_events = calendar.get_events_for_user(other_email, max_results=3)
            print(f"  ✅ Successfully accessed {other_email}'s calendar")
            print(f"     Found {len(other_events)} upcoming events")
        except Exception as e:
            print(f"  ⚠️  Could not access {other_email}'s calendar: {e}")
            print("     This user may have privacy settings enabled")
    
    print()
    print("=" * 60)
    print("✅ Setup verification complete!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  • See example_org_access.py for usage examples")
    print("  • Read ORG_SETUP_GUIDE.md for advanced features")
    print()
    
    return True

if __name__ == "__main__":
    try:
        success = verify_setup()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nVerification cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        sys.exit(1)