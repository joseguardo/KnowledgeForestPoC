-- Add 'folder' to the pointer_type enum so SharePoint/OneDrive folders are
-- first-class structure nodes. Mirrors the fund-type migration: a new enum value
-- cannot be referenced in the same transaction that adds it, so this stands alone.
alter type public.pointer_type add value if not exists 'folder';

-- Describe the new type + edges for agents/skills (mirrors existing rows).
-- schema_vocabulary.category is constrained to (pointer_type | edge_type | attribute_key).
insert into public.schema_vocabulary (term, category, description)
values
  (
    'folder',
    'pointer_type',
    'A SharePoint/OneDrive folder mirrored as a body-less structure node. '
    'canonical_key is msgraph:{entraTenantId}:drive/{driveId}/item/{itemId} '
    '(stable across rename/move within a drive). Children link UP via folder_of '
    '(subfolders) and documents_of (files). A top company/fund folder also links '
    'folder_of to its company/fund entity pointer. Path/name/web_url live in '
    'metadata (mutable); contents are fetched on demand from Graph, never stored.'
  ),
  (
    'folder_of',
    'edge_type',
    'Hierarchy/ownership edge for the SharePoint skeleton: a folder pointer '
    '-folder_of-> its parent folder, and a top company/fund folder -folder_of-> '
    'its company/fund entity pointer. To list a company/fund documents, traverse '
    'INBOUND folder_of from the entity to its folder, then INBOUND folder_of + '
    'documents_of recursively (depth ~6) to reach document pointers.'
  ),
  (
    'documents_of',
    'edge_type',
    'SharePoint skeleton edge: a file pointer (type=document, empty body) '
    '-documents_of-> its parent folder pointer. Fetch the file bytes on demand via '
    'GET /drives/{driveId}/items/{itemId}/content (derivable from the msgraph: key).'
  )
on conflict do nothing;
