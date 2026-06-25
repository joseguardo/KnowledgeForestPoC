"""
Report Generator for Meeting Attendees
Generates simple reports about meeting participants
"""

from datetime import datetime
import os

class ReportGenerator:
    """Generate reports about meeting attendees"""
    
    def __init__(self, reports_dir='reports'):
        """
        Initialize report generator
        
        Args:
            reports_dir: Directory to save reports
        """
        self.reports_dir = reports_dir
        self._ensure_reports_dir()
    
    def _ensure_reports_dir(self):
        """Create reports directory if it doesn't exist"""
        if not os.path.exists(self.reports_dir):
            os.makedirs(self.reports_dir)
    
    def extract_attendees(self, event):
        """
        Extract attendee information from event
        
        Args:
            event: Event dictionary from Google Calendar
            
        Returns:
            List of attendee dictionaries with email and name
        """
        attendees = event.get('attendees', [])
        
        attendee_info = []
        for attendee in attendees:
            info = {
                'email': attendee.get('email', 'N/A'),
                'name': attendee.get('displayName', attendee.get('email', 'Unknown').split('@')[0]),
                'status': attendee.get('responseStatus', 'unknown'),
                'organizer': attendee.get('organizer', False)
            }
            attendee_info.append(info)
        
        return attendee_info
    
    def generate_report(self, event):
        """
        Generate a simple text report for a meeting
        
        Args:
            event: Event dictionary from Google Calendar
            
        Returns:
            Path to the generated report file
        """
        # Extract event details
        event_id = event.get('id', 'unknown')
        summary = event.get('summary', 'Sin título')
        description = event.get('description', 'Sin descripción')
        location = event.get('location', 'Sin ubicación')
        start_time = event['start'].get('dateTime', event['start'].get('date'))
        
        # Extract attendees
        attendees = self.extract_attendees(event)
        
        # Generate report content
        report_lines = []
        report_lines.append("=" * 70)
        report_lines.append(f"INFORME DE REUNIÓN")
        report_lines.append("=" * 70)
        report_lines.append(f"\n📅 Evento: {summary}")
        report_lines.append(f"🕐 Hora: {start_time}")
        report_lines.append(f"📍 Ubicación: {location}")
        report_lines.append(f"\n📝 Descripción:\n{description}")
        report_lines.append(f"\n{'=' * 70}")
        report_lines.append(f"PARTICIPANTES ({len(attendees)} personas)")
        report_lines.append("=" * 70)
        
        if not attendees:
            report_lines.append("\n⚠️  No hay asistentes registrados para esta reunión")
        else:
            for i, attendee in enumerate(attendees, 1):
                report_lines.append(f"\n{i}. {attendee['name']}")
                report_lines.append(f"   ✉️  Email: {attendee['email']}")
                report_lines.append(f"   📊 Estado: {self._translate_status(attendee['status'])}")
                if attendee['organizer']:
                    report_lines.append(f"   👤 Rol: Organizador")
                
                # Aquí podrías agregar más información sobre el asistente
                # Por ejemplo, búsqueda en LinkedIn, CRM, base de datos interna, etc.
                report_lines.append(f"   💡 Notas: [Agregar contexto sobre este participante]")
        
        report_lines.append(f"\n{'=' * 70}")
        report_lines.append(f"PREPARACIÓN SUGERIDA")
        report_lines.append("=" * 70)
        report_lines.append("\n🎯 Puntos a considerar:")
        report_lines.append("   • Revisar el contexto de la reunión")
        report_lines.append("   • Preparar materiales necesarios")
        report_lines.append("   • Verificar objetivos de la reunión")
        
        report_lines.append(f"\n{'=' * 70}")
        report_lines.append(f"Informe generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("=" * 70)
        
        # Save report to file
        filename = self._generate_filename(event_id, summary, start_time)
        filepath = os.path.join(self.reports_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report_lines))
        
        return filepath
    
    def _translate_status(self, status):
        """Translate response status to Spanish"""
        translations = {
            'accepted': '✅ Confirmado',
            'declined': '❌ Rechazado',
            'tentative': '⏳ Tentativo',
            'needsAction': '❓ Sin respuesta',
            'unknown': '❓ Desconocido'
        }
        return translations.get(status, status)
    
    def _generate_filename(self, event_id, summary, start_time):
        """Generate a filename for the report"""
        # Clean summary for filename
        clean_summary = "".join(c for c in summary if c.isalnum() or c in (' ', '-', '_')).strip()
        clean_summary = clean_summary.replace(' ', '_')[:30]  # Limit length
        
        # Extract date from start_time
        try:
            if 'T' in start_time:
                date_str = start_time.split('T')[0]
            else:
                date_str = start_time
        except:
            date_str = datetime.now().strftime('%Y-%m-%d')
        
        return f"{date_str}_{clean_summary}_{event_id[:8]}.txt"
    
    def print_report(self, report_path):
        """Print report to console"""
        with open(report_path, 'r', encoding='utf-8') as f:
            print(f.read())