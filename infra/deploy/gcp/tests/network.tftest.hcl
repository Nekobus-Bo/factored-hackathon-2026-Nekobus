# The compose networks on the VPC (ADR-0006 on Cloud Run, ADR-0015): which subnet each
# workload is on, which subnet has NAT, and the firewall that keeps edge away from core data.

mock_provider "google" {
  source = "./tests/mocks/google"
}

mock_provider "google-beta" {
  source = "./tests/mocks/google-beta"
}

variables {
  project_id           = "pb-test-project"
  github_repository    = "someone/pattern-blue-gcp"
  github_repository_id = "123456"
}

run "workloads_sit_in_their_zone" {
  command = apply

  assert {
    condition = alltrue([
      for name, subnet in { "banking-core" = "core", "encoder" = "edge", "orchestrator" = "egress", "web-client" = "edge", "web-backoffice" = "edge" } :
      google_cloud_run_v2_service.svc[name].template[0].vpc_access[0].network_interfaces[0].subnetwork == google_compute_subnetwork.subnet[subnet].id
    ])
    error_message = "A service is on the wrong subnet."
  }

  assert {
    condition = alltrue([
      for name, tag in { "banking-core" = "pb-core", "encoder" = "pb-edge", "orchestrator" = "pb-edge", "web-client" = "pb-edge", "web-backoffice" = "pb-edge" } :
      tolist(google_cloud_run_v2_service.svc[name].template[0].vpc_access[0].network_interfaces[0].tags) == tolist([tag])
    ])
    error_message = "A service carries the wrong network tag."
  }

  assert {
    condition = alltrue([
      for name, subnet in { "migrate" = "core", "seed" = "core", "netcheck" = "edge" } :
      google_cloud_run_v2_job.job[name].template[0].template[0].vpc_access[0].network_interfaces[0].subnetwork == google_compute_subnetwork.subnet[subnet].id
    ])
    error_message = "A job is on the wrong subnet: migrate and seed belong to core, netcheck to edge."
  }

  # Everything goes through the VPC, so the firewall and the missing NAT apply to it.
  assert {
    condition = alltrue(concat(
      [for service in google_cloud_run_v2_service.svc : service.template[0].vpc_access[0].egress == "ALL_TRAFFIC"],
      [for job in google_cloud_run_v2_job.job : job.template[0].template[0].vpc_access[0].egress == "ALL_TRAFFIC"],
    ))
    error_message = "Every workload must route all egress into the VPC."
  }
}

run "only_the_orchestrator_reaches_the_internet" {
  command = apply

  assert {
    condition = (
      google_compute_router_nat.egress.source_subnetwork_ip_ranges_to_nat == "LIST_OF_SUBNETWORKS"
      && toset([for subnet in google_compute_router_nat.egress.subnetwork : subnet.name]) == toset([google_compute_subnetwork.subnet["egress"].id])
    )
    error_message = "Cloud NAT must cover the egress subnet and nothing else."
  }

  assert {
    condition     = alltrue([for subnet in google_compute_subnetwork.subnet : subnet.private_ip_google_access])
    error_message = "Every subnet needs Private Google Access: internal run.app calls and Google APIs go through it."
  }
}

run "edge_cannot_reach_core_data" {
  command = apply

  assert {
    condition = (
      google_compute_firewall.deny_edge_to_core_data.direction == "EGRESS"
      && google_compute_firewall.deny_edge_to_core_data.priority < 1000
      && google_compute_firewall.deny_edge_to_core_data.target_tags == toset(["pb-edge"])
      && google_compute_firewall.deny_edge_to_core_data.destination_ranges == toset(["10.20.0.0/20"])
      && [for rule in google_compute_firewall.deny_edge_to_core_data.deny : rule.protocol] == ["all"]
    )
    error_message = "Egress from pb-edge to the psa-core range must be denied, above the implied allow."
  }

  assert {
    condition = (
      google_compute_firewall.deny_core_to_edge_data.target_tags == toset(["pb-core"])
      && google_compute_firewall.deny_core_to_edge_data.destination_ranges == toset(["10.21.0.0/24"])
    )
    error_message = "Egress from pb-core to the psa-edge range must be denied."
  }

  # The deny rule is only as good as the addresses behind it.
  assert {
    condition = (
      google_sql_database_instance.bank.settings[0].ip_configuration[0].allocated_ip_range == google_compute_global_address.psa["core"].name
      && google_redis_instance.zone["core"].reserved_ip_range == google_compute_global_address.psa["core"].name
      && google_redis_instance.zone["edge"].reserved_ip_range == google_compute_global_address.psa["edge"].name
    )
    error_message = "Cloud SQL and redis-core must be in psa-core, redis-edge in psa-edge."
  }

  assert {
    condition     = !google_sql_database_instance.bank.settings[0].ip_configuration[0].ipv4_enabled
    error_message = "Cloud SQL has no public address."
  }
}

run "netcheck_probes_the_real_addresses" {
  command = apply

  assert {
    condition = one([
      for env in google_cloud_run_v2_job.job["netcheck"].template[0].template[0].containers[0].env : env.value if env.name == "NETCHECK_BLOCKED"
    ]) == "10.20.0.3:5432,10.20.1.4:6379"
    error_message = "netcheck must probe Cloud SQL and redis-core."
  }
}
