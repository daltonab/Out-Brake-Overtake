import heroImage from '../assets/open-wheel-hero.png'

export function HomePage() {
  return (
    <section className="home-hero">
      <img src={heroImage} alt="Original open-wheel race car on a dark circuit" />
      <div className="home-copy">
        <p className="eyebrow">Open-source race analysis</p>
        <h2>Precision beyond the pass.</h2>
        <p>Out Brake, Overtake explores how braking, speed, and race context shape decisive moves in Formula 1.</p>
        <p className="home-note">Built for transparent analysis, shared learning, and better questions—not proprietary race intelligence.</p>
        <p className="home-disclaimer">Out Brake, Overtake is an independent community project and is not affiliated with or endorsed by Formula 1, the FIA, any team, driver, or OpenF1. Formula 1, FIA, team, and driver names and marks belong to their respective owners.</p>
      </div>
    </section>
  )
}
