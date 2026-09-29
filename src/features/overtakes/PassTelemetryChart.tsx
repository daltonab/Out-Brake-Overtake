import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { DriverBrakingOvertake } from './overtakeService'

type Props = { event: DriverBrakingOvertake; passerName: string; defenderName: string }

export function PassTelemetryChart({ event, passerName, defenderName }: Props) {
  const data = chartData(event)
  const onsetLabel = `${(event.brakeOnsetAdvantageMs / 1000).toFixed(2)}s later`
  return <section className="pass-telemetry" aria-label="Pass telemetry">
    <div className="telemetry-heading"><div><p className="eyebrow">Pass telemetry</p><h3>{passerName} vs {defenderName}</h3><p>Ten-second window ending at the completed pass. {passerName} brakes {onsetLabel}.</p></div><div className="telemetry-key" aria-label="Telemetry marker key"><span className="pass">Pass · 0.0s</span><span className="passer">Passer brakes</span><span className="defender">Defender brakes</span></div></div>
    <TelemetryChart title="Speed" unit="km/h" data={data} passerKey="passerSpeed" defenderKey="defenderSpeed" event={event} />
    <TelemetryChart title="Brake application" unit="%" data={data} passerKey="passerBrake" defenderKey="defenderBrake" event={event} />
  </section>
}

function TelemetryChart({ title, unit, data, passerKey, defenderKey, event }: { title: string; unit: string; data: Record<string, number>[]; passerKey: string; defenderKey: string; event: DriverBrakingOvertake }) {
  return <div className="telemetry-chart"><h4>{title} <span>{unit}</span></h4><ResponsiveContainer width="100%" height={190}><LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -16 }}><CartesianGrid stroke="#303239" vertical={false} /><XAxis dataKey="t" type="number" domain={[-8000, 2000]} tickFormatter={(value) => `${(value / 1000).toFixed(0)}s`} stroke="#858a94" fontSize={11} /><YAxis stroke="#858a94" fontSize={11} width={40} /><Tooltip labelFormatter={(value) => `${(Number(value) / 1000).toFixed(2)}s from pass`} contentStyle={{ background: '#111214', border: '1px solid #43464e' }} /><Legend wrapperStyle={{ fontSize: 12 }} /><ReferenceLine x={0} stroke="#ffffff" strokeWidth={2.5} /><ReferenceLine x={event.passerBrakeOffsetMs} stroke="#e13c36" strokeWidth={1.5} strokeDasharray="4 3" /><ReferenceLine x={event.defenderBrakeOffsetMs} stroke="#8fa8c8" strokeWidth={1.5} strokeDasharray="4 3" /><Line type="monotone" dataKey={passerKey} name="Passer" stroke="#e13c36" strokeWidth={2.5} dot={false} connectNulls /><Line type="monotone" dataKey={defenderKey} name="Defender" stroke="#8fa8c8" strokeWidth={2.5} dot={false} connectNulls /></LineChart></ResponsiveContainer></div>
}

function chartData(event: DriverBrakingOvertake) {
  const rows = new Map<number, Record<string, number>>()
  for (const point of event.passerTrace) rows.set(point.t, { ...(rows.get(point.t) ?? { t: point.t }), passerSpeed: point.speed, passerBrake: point.brake })
  for (const point of event.defenderTrace) rows.set(point.t, { ...(rows.get(point.t) ?? { t: point.t }), defenderSpeed: point.speed, defenderBrake: point.brake })
  return [...rows.values()].sort((a, b) => a.t - b.t)
}
