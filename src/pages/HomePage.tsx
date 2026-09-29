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
      </div>
    </section>
  )
}
