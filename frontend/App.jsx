import { useEffect, useState } from "react";
import "./App.css";

function App() {
  const [about, setAbout] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("http://127.0.0.1:5000/api/about")
      .then((response) => {
        if (!response.ok) {
          throw new Error("Could not connect to database");
        }

        return response.json();
      })
      .then((data) => {
        setAbout(data);
      })
      .catch((err) => {
        setError(err.message);
      });
  }, []);

  if (error) {
    return (
      <div className="page">
        <div className="card">
          <p className="team">TEAM 02</p>

          <h1>Good Driver Incentive Program</h1>

          <div className="error">
            Database Connection: Failed
          </div>

          <p>{error}</p>
        </div>
      </div>
    );
  }

  if (!about) {
    return (
      <div className="page">
        <div className="card">
          <p className="team">TEAM 02</p>
          <h1>Good Driver Incentive Program</h1>
          <p>Loading database information...</p>
        </div>
      </div>
    );
  }

  const releaseDate = new Date(
    about.release_date
  ).toLocaleDateString("en-US", {
    timeZone: "UTC",
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <div className="page">
      <div className="card">

        <p className="team">
          TEAM {about.team_number}
        </p>

        <h1>{about.product_name}</h1>

        <p className="description">
          {about.product_description}
        </p>

        <div className="details">
          <p>
            <strong>Version:</strong>{" "}
            {about.version_number}
          </p>

          <p>
            <strong>Release Date:</strong>{" "}
            {releaseDate}
          </p>
        </div>

        <div className="status">
          Database Connection: Connected ✓
        </div>

        <p className="source">
          Information loaded from Team02_DB on AWS RDS
        </p>

      </div>
    </div>
  );
}

export default App;