import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AnalysisFilters } from '../features/filters/AnalysisFilters'
import { getDriversForRace, getRaceSession, getRacesForYear } from '../features/filters/filterService'
import { OvertakeWorkspace } from '../features/overtakes/OvertakeWorkspace'
import { useDriverBrakingOvertakes } from '../features/overtakes/useBrakingOvertakes'
import { HomePage } from './HomePage'
import { ModelPage } from './ModelPage'
import { AboutModelPage } from './AboutModelPage'
import { OvertakeLines } from '../components/ApexMark'

export function AnalysisPage() {
  const [activeTab, setActiveTab] = useState<'home' | 'overtakes' | 'model' | 'about-model'>('home')
  const [year, setYear] = useState(2026)
  const [meetingKey, setMeetingKey] = useState<number>()
  const [driverNumber, setDriverNumber] = useState<number>()
  const races = useQuery({ queryKey: ['races', year], queryFn: () => getRacesForYear(year) })
  const session = useQuery({ queryKey: ['race-session', meetingKey], queryFn: () => getRaceSession(meetingKey!), enabled: meetingKey !== undefined })
  const drivers = useQuery({ queryKey: ['race-drivers', session.data?.session_key], queryFn: () => getDriversForRace(session.data!.session_key), enabled: session.data !== undefined })
  const overtakes = useDriverBrakingOvertakes(session.data?.session_key, driverNumber)
  useEffect(() => { setMeetingKey(undefined); setDriverNumber(undefined) }, [year])
  useEffect(() => { setDriverNumber(undefined) }, [meetingKey])

  return (
    <main className="app-shell">
      <div className="app-topbar">
        <header className="app-header">
          <div className="masthead-mark" aria-hidden="true"><i /><i /><i /></div>
          <p className="eyebrow">Historical race analysis</p>
          <h1>Out Brake, Overtake</h1>
        </header>
        <OvertakeLines />
        <aside className="project-status" aria-label="Project status">
          <p className="eyebrow">Project status</p>
          <strong>Built in public</strong>
          <span>Open source · Historical data</span>
        </aside>
      </div>
      <nav className="page-tabs" aria-label="Data views">
        <button className={activeTab === 'home' ? 'active' : ''} onClick={() => setActiveTab('home')}>Home</button>
        <button className={activeTab === 'model' ? 'active' : ''} onClick={() => setActiveTab('model')}>Predictive Model</button>
        <button className={activeTab === 'overtakes' ? 'active' : ''} onClick={() => setActiveTab('overtakes')}>Overtakes</button>
        <button className={activeTab === 'about-model' ? 'active' : ''} onClick={() => setActiveTab('about-model')}>About Our Model</button>
      </nav>
      {activeTab === 'home' ? <HomePage /> : activeTab === 'model' ? <ModelPage /> : activeTab === 'about-model' ? <AboutModelPage /> : <>
        <AnalysisFilters year={year} raceKey={meetingKey} driverNumber={driverNumber} races={races.data ?? []} drivers={drivers.data ?? []} disabled={races.isLoading || session.isLoading || drivers.isLoading} onYearChange={setYear} onRaceChange={setMeetingKey} onDriverChange={setDriverNumber} />
        <OvertakeWorkspace driverNumber={driverNumber} drivers={drivers.data ?? []} overtakes={overtakes.data} isLoading={overtakes.isLoading} error={overtakes.error} />
      </>}
    </main>
  )
}
