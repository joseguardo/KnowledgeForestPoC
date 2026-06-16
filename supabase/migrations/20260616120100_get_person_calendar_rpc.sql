-- Returns a person's calendar: every 'event' pointer they are connected to,
-- in either direction (they attended it, or they are an attendee of it),
-- ordered by occurred_at. For each event we also return its co-attendees
-- (other people/companies linked to the same event) so the timeline can show
-- "who was in the room". SECURITY INVOKER (default) so RLS / can_read_class
-- on pointers + edges still applies to the caller.
create or replace function public.get_person_calendar(p_person_id uuid)
returns jsonb
language sql
stable
as $$
  with related_events as (
    -- Events the person attended (person --attended--> event)
    select e.target_id as event_id
    from public.edges e
    where e.source_id = p_person_id and e.relationship_type = 'attended'
    union
    -- Events that list the person as a participant (event --attended_by--> person)
    select e.source_id as event_id
    from public.edges e
    where e.target_id = p_person_id and e.relationship_type = 'attended_by'
  ),
  events as (
    select p.id, p.label, p.occurred_at, p.metadata
    from public.pointers p
    join related_events re on re.event_id = p.id
    where p.type = 'event'
  ),
  attendees as (
    -- co-participants of each event (exclude the person themselves)
    select ev.id as event_id,
           jsonb_agg(
             distinct jsonb_build_object('id', a.id, 'label', a.label, 'type', a.type)
           ) as people
    from events ev
    join public.edges e
      on (e.source_id = ev.id and e.relationship_type in ('attended_by', 'regarding'))
    join public.pointers a on a.id = e.target_id and a.id <> p_person_id
    group by ev.id
  )
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'id', ev.id,
        'label', ev.label,
        'occurred_at', ev.occurred_at,
        'metadata', coalesce(ev.metadata, '{}'::jsonb),
        'attendees', coalesce(at.people, '[]'::jsonb)
      )
      order by ev.occurred_at desc nulls last
    ),
    '[]'::jsonb
  )
  from events ev
  left join attendees at on at.event_id = ev.id;
$$;

grant execute on function public.get_person_calendar(uuid) to anon, authenticated;
