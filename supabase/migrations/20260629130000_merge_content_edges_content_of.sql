-- Combine every "document is the content of X" edge type into one: `content_of`.
--   communication_content (document --> communication: email/meeting body)
--   note_about            (document --> entity: a CRM note)
--   event_details         (document --> event: a calendar description)
--   meeting_notes         (document --> event: a meeting summary)
-- all point from a content document to the thing it is the content of. Unify them.
-- relationship_type is free text (no enum/check), so this is a plain UPDATE.

update edges
   set relationship_type = 'content_of'
 where relationship_type in (
   'communication_content', 'note_about', 'event_details', 'meeting_notes'
 );
