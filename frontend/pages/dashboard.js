import { useEffect, useState } from "react";

export default function Dashboard() {
    const [servers, setServers] = useState([]);

    useEffect(() => {
        fetch("/api/servers/")
            .then((res) => res.json())
            .then((data) => setServers(data));
    }, []);

    return (
        <div className="p-5">
            <h1 className="text-xl font-bold">Dashboard</h1>
            <ul>
                {servers.map((server, index) => (
                    <li key={index}>{server.name} - {server.type}</li>
                ))}
            </ul>
        </div>
    );
}
