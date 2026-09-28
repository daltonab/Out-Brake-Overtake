export type OpenF1Record = {
  meeting_key: number
  session_key: number
}

export type CarData = OpenF1Record & {
  date: string
  driver_number: number
  speed: number
  throttle: number
  brake: number
  rpm: number
  n_gear: number
  drs: number
}

export type Overtake = OpenF1Record & {
  date: string
  overtaking_driver_number: number
  overtaken_driver_number: number
  position: number
}

export type Meeting = {
  meeting_key: number
  meeting_name: string
  date_start: string
  year: number
}

export type Session = OpenF1Record & {
  session_name: string
  session_type: string
  date_start: string
  year: number
}

export type Driver = OpenF1Record & {
  driver_number: number
  full_name: string
  name_acronym: string
  team_name: string
  team_colour: string
}

export type Lap = OpenF1Record & {
  date_start: string
  driver_number: number
  lap_number: number
  lap_duration: number | null
}
