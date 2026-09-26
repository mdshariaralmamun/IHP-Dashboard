import { useEffect, useState } from 'react';

/**
 * Hook that auto-populates PI and Location from the O&M Tracking Sheet
 * at project intake form mount.
 *
 * Logic:
 * 1. Check if an O&M sheet is cached in the app's corpus (uploaded via /api/admin/import/om)
 * 2. If O&M available, pull PI from the sheet's requestor field and Location from
 *    detail_location field (fallback to general location if detail is empty)
 * 3. Mark which fields are auto-populated so the form can distinguish user-edited
 *    values from O&M-sourced values
 * 4. Re-fetch if the form's PR number or title changes (e.g. on re-visit)
 */
export function useOvmAutoPopulate(prNumber: string, prTitle: string) {
  const [omPi, setOmPi] = useState<string>('');
  const [omLocation, setOmLocation] = useState<string>('');
  const [omDetailLocation, setOmDetailLocation] = useState<string>('');
  const [omSource, setOmSource] = useState<'none' | 'om' | 'pr'>('none');
  const [omPopulatedAt, setOmPopulatedAt] = useState<string>('');

  const [piAuto, setPiAuto] = useState<boolean>(false);
  const [locationAuto, setLocationAuto] = useState<boolean>(false);

  useEffect(() => {
    async function fetchOmData() {
      try {
        // Import the API client lazily to avoid circular deps
        const { listCorpus } = await import('@/lib/api');
        const omDocs = await listCorpus();

        // Find the most recently uploaded O&M sheet
        const omDoc = omDocs
          .filter((d) => d.filename?.toLowerCase().includes('om'))
          .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))[0];

        if (!omDoc) {
          setOmPi('');
          setOmLocation('');
          setOmDetailLocation('');
          setOmSource('none');
          setPiAuto(false);
          setLocationAuto(false);
          return;
        }

        // Pull PI from O&M sheet's requestor field (this is the source-of-truth per spec).
        // If the requestor looks like multiple IHP team members (comma-separated), the
        // form can still offer it for manual override.
        const rec = omDoc as unknown as Record<string, unknown>;
        const piFromOm = (rec.pi_name as string) || (rec.requestor as string) || '';

        // Pull Location: prefer detail_location (more granular), fall back to general location
        const detailLoc = (rec.location_details as string) || '';
        const generalLoc = (rec.location as string) || '';
        const locationFromOm = detailLoc || generalLoc || '';

        setOmPi(piFromOm);
        setOmLocation(locationFromOm);
        setOmDetailLocation(detailLoc);
        setOmSource('om');
        setOmPopulatedAt(new Date().toISOString());
        setPiAuto(true);
        setLocationAuto(true);
      } catch (e) {
        console.error('OVM auto-populate error:', e);
        setOmPi('');
        setOmLocation('');
        setOmDetailLocation('');
        setOmSource('none');
        setPiAuto(false);
        setLocationAuto(false);
      }
    }

    fetchOmData();
  }, [prNumber, prTitle]);

  return {
    omPi,
    omLocation,
    omDetailLocation,
    omSource,
    omPopulatedAt,
    piAuto,
    locationAuto,
  };
}