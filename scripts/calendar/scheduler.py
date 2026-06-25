"""
Meeting Report Scheduler
Automatically checks calendar and generates reports 15 minutes before meetings
"""

import time
import json
import os
from datetime import datetime
from client import CalendarConnector
from report_generator import ReportGenerator

class MeetingScheduler:
    """Scheduler that monitors calendar and generates reports"""

    def __init__(self, check_interval_minutes=5, warning_minutes=15, tracking_file='processed_events.json', 
                 credentials_file='OAuth.json', token_file='token.pickle', 
                 service_account_file=None, delegated_user=None, organizer_email=None):
        """
        Initialize the scheduler
        
        Args:
            check_interval_minutes: How often to check the calendar (default: 5 minutes)
            warning_minutes: How many minutes before meeting to generate report (default: 15)
            tracking_file: File to track processed events
            credentials_file: Path to OAuth2 credentials JSON (for personal use)
            token_file: Path to store authentication token
            service_account_file: Path to service account JSON (for org-wide access)
            delegated_user: Email of user to impersonate (required with service account)
            organizer_email: Email to filter events by organizer (if None, will detect automatically)
        """
        self.check_interval = check_interval_minutes * 60  # Convert to seconds
        self.warning_minutes = warning_minutes
        self.tracking_file = tracking_file
        
        # Initialize calendar connector with proper credentials
        self.calendar = CalendarConnector(
            credentials_file=credentials_file,
            token_file=token_file,
            service_account_file=service_account_file,
            delegated_user=delegated_user
        )
        
        self.report_gen = ReportGenerator()
        self.processed_events = self._load_processed_events()
        
        # Set organizer email (auto-detect if not provided)
        if organizer_email:
            self.correo_cliente = organizer_email
        else:
            self.correo_cliente = self.calendar.get_current_user_email()
        
        print(f"🚀 Scheduler iniciado")
        print(f"   📧 Email del organizador: {self.correo_cliente}")
        print(f"   ⏱️  Revisando calendario cada {check_interval_minutes} minutos")
        print(f"   ⚠️  Generando informes {warning_minutes} minutos antes de reuniones")
        print(f"   🔒 Filtrando solo eventos donde eres organizador")
        print("=" * 70)
    
    def _load_processed_events(self):
        """Load list of already processed event IDs"""
        if os.path.exists(self.tracking_file):
            with open(self.tracking_file, 'r') as f:
                return json.load(f)
        return {}
    
    def _save_processed_events(self):
        """Save list of processed event IDs"""
        with open(self.tracking_file, 'w') as f:
            json.dump(self.processed_events, f, indent=2)
    
    def _mark_as_processed(self, event_id):
        """Mark an event as processed"""
        self.processed_events[event_id] = {
            'processed_at': datetime.now().isoformat(),
            'timestamp': time.time()
        }
        self._save_processed_events()
    
    def _is_processed(self, event_id):
        """Check if event has already been processed"""
        return event_id in self.processed_events
    
    def _cleanup_old_entries(self, days_to_keep=7):
        """Remove old entries from tracking file"""
        current_time = time.time()
        cutoff_time = current_time - (days_to_keep * 24 * 60 * 60)
        
        to_remove = []
        for event_id, data in self.processed_events.items():
            if data.get('timestamp', 0) < cutoff_time:
                to_remove.append(event_id)
        
        for event_id in to_remove:
            del self.processed_events[event_id]
        
        if to_remove:
            self._save_processed_events()
            print(f"🧹 Limpieza: {len(to_remove)} eventos antiguos eliminados del tracking")
    
    def check_upcoming_meetings(self):
        """Check for upcoming meetings and generate reports if needed"""
        try:
            # Get events in the next 15-20 minutes window
            # We check a bit ahead to ensure we don't miss anything
            events = self.calendar.get_events_in_timeframe(
                minutes_from_now_start=self.warning_minutes - 10,  # 13 minutes
                minutes_from_now_end=self.warning_minutes + 5     # 20 minutes
            )
            
            if not events:
                return
            
            # Filter events where you are the organizer
            my_events = self.calendar.filter_events_by_organizer(events, self.correo_cliente)
            
            if not my_events:
                return
            
            print(f"\n⏰ {datetime.now().strftime('%H:%M:%S')} - Encontrados {len(my_events)} eventos próximos donde eres organizador")
            
            for event in my_events:
                event_id = event.get('id')
                summary = event.get('summary', 'Sin título')
                start_time = event['start'].get('dateTime', event['start'].get('date'))
                
                # Skip if already processed
                if self._is_processed(event_id):
                    print(f"   ⏭️  '{summary}' ya procesado anteriormente")
                    continue
                
                # Generate report
                print(f"   📊 Generando informe para: '{summary}'")
                print(f"      🕐 Hora de inicio: {start_time}")
                
                try:
                    report_path = self.report_gen.generate_report(event)
                    print(f"      ✅ Informe guardado: {report_path}")
                    
                    # Mark as processed
                    self._mark_as_processed(event_id)
                    
                    # Optionally print the report to console
                    # self.report_gen.print_report(report_path)
                    
                except Exception as e:
                    print(f"      ❌ Error generando informe: {e}")
        
        except Exception as e:
            print(f"❌ Error revisando calendario: {e}")
    
    def run(self):
        """Main loop - runs indefinitely"""
        print(f"\n▶️  Iniciando monitoreo de calendario...")
        print(f"Presiona Ctrl+C para detener\n")
        
        iteration = 0
        try:
            while True:
                iteration += 1
                print(f"🔄 Revisión #{iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                
                self.check_upcoming_meetings()
                
                # Cleanup old entries every 50 iterations
                if iteration % 50 == 0:
                    self._cleanup_old_entries()
                
                print(f"   💤 Esperando {self.check_interval // 60} minutos hasta próxima revisión...")
                print("-" * 70)
                
                time.sleep(self.check_interval)
        
        except KeyboardInterrupt:
            print("\n\n⏹️  Scheduler detenido por el usuario")
            print(f"Total de eventos procesados: {len(self.processed_events)}")
    
    def test_mode(self):
        """Run a single check without looping (for testing)"""
        print("🧪 MODO TEST - Ejecutando una sola revisión...\n")
        self.check_upcoming_meetings()
        print("\n✅ Test completado")


if __name__ == "__main__":
    # OPCIÓN 1: Uso básico con OAuth (autenticación personal)
    # Detectará automáticamente tu email como organizador
    #scheduler = MeetingScheduler(
    #    check_interval_minutes=5,  # Revisar cada 5 minutos
    #    warning_minutes=15         # Generar informe 15 minutos antes
    #)

    # OPCIÓN 2: Con email específico del organizador
    # scheduler = MeetingScheduler(
    #     check_interval_minutes=5,
    #     warning_minutes=15,
    #     organizer_email="tu-email@ejemplo.com"  # Especificar email manualmente
    # )
    
    # OPCIÓN 3: Con Service Account (acceso a múltiples usuarios)
    scheduler = MeetingScheduler(
         check_interval_minutes=5,
        warning_minutes=15,
        service_account_file='service-account.json',
        delegated_user='jose@kiboventures.com',
        organizer_email='juan@kiboventures.com'
    )
    
    # Para ejecutar una sola prueba sin loop:
    # scheduler.test_mode()
    
    # Para ejecutar en modo continuo (producción):
    scheduler.run()