'use client';

import AuthGuard from '@/components/AuthGuard';
import Header from '@/components/Header';
import PhaseBoard from '@/components/PhaseBoard';
import { useUser } from '@/lib/useUser';

/** The Design board: whose move is it, and what blinks because it is ours. */
export default function DesignBoardPage() {
  const { user } = useUser();
  return (
    <AuthGuard>
      <div className='min-h-screen bg-apple-surface/50'>
        <Header user={user} />
        <main className='mx-auto max-w-7xl space-y-4 px-4 py-8'>
          <div>
            <h1 className='text-2xl font-bold tracking-tight text-apple-text'>Design board</h1>
            <p className='mt-1 text-sm text-apple-muted'>
              MOM and Project Summary sent/pending, whose court each PR is in, assignment,
              follow-up and one-click email to the PI. Blinking rows are OUR move.
            </p>
          </div>
          <PhaseBoard phase='design' />
        </main>
      </div>
    </AuthGuard>
  );
}
