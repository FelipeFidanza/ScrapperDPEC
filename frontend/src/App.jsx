// Base para el futuro frontend: calendario de cortes (GET /cortes), lista de zonas para
// suscribirse (GET /zonas), historial y métricas.
export default function App() {
  return (
    <main style={{ fontFamily: "system-ui, sans-serif", margin: "2rem auto", maxWidth: "40rem", padding: "0 1rem" }}>
      <h1>Cortes de luz en Corrientes</h1>
      <p>Próximamente: calendario de cortes programados y suscripción por zona.</p>
      <p>
        <small>Proyecto personal, sin relación con la DPEC.</small>
      </p>
    </main>
  );
}
